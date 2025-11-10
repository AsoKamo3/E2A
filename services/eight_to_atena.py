# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.5.8
# - 既存ロジックは維持
# - v2.5.8:
#     * 法人格除去強化版:
#         - 一般社団法人／公益財団法人 等を前方優先で除去
#         - 英文法人格 (Co., Ltd., Inc., Corporation, Company, LLC など) の後方除去を改善
#         - 「一般」「公益」などの接頭語単独残りを除去
#         - 空白・中点・句読点を含む残滓除去を強化

from __future__ import annotations

import io
import os
import json
import csv
import math
import re
from typing import List, Tuple, Dict, Any, Optional

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES
from utils.kana import to_katakana_guess as _to_kata

__version__ = "v2.5.8"

# ===== 宛名職人ヘッダ（完全列） =====
ATENA_HEADERS: List[str] = [
    "姓","名","姓かな","名かな","姓名","姓名かな","ミドルネーム","ミドルネームかな","敬称",
    "ニックネーム","旧姓","宛先","自宅〒","自宅住所1","自宅住所2","自宅住所3","自宅電話",
    "自宅IM ID","自宅E-mail","自宅URL","自宅Social",
    "会社〒","会社住所1","会社住所2","会社住所3","会社電話","会社IM ID","会社E-mail",
    "会社URL","会社Social",
    "その他〒","その他住所1","その他住所2","その他住所3","その他電話","その他IM ID",
    "その他E-mail","その他URL","その他Social",
    "会社名かな","会社名","部署名1","部署名2","役職名",
    "連名","連名ふりがな","連名敬称","連名誕生日",
    "メモ1","メモ2","メモ3","メモ4","メモ5",
    "備考1","備考2","備考3","誕生日","性別","血液型","趣味","性格"
]

# Eight 固定ヘッダ
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ============================================================
# 電話・住所・部署などの共通整形ユーティリティ（v2.5.7と同一）
# ============================================================

def _clean_key(k: str) -> str:
    return (k or "").lstrip("\ufeff").strip()

def _clean_row(row: dict) -> dict:
    return {_clean_key(k): (v or "") for k, v in row.items()}

SEP_PATTERN = re.compile(r'(?:／|/|・|,|、|｜|\||\s)+')

def _split_department_half(s: str) -> tuple[str, str]:
    s = (s or "").strip()
    if not s:
        return "", ""
    tokens = [t for t in SEP_PATTERN.split(s) if t]
    if len(tokens) <= 1:
        return s, ""
    n = len(tokens)
    k = math.ceil(n / 2.0)
    left = "　".join(tokens[:k])
    right = "　".join(tokens[k:]) if k < n else ""
    return left, right

_MOBILE_PREFIXES = ("070", "080", "090")

def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _format_by_area(d: str) -> str:
    ac = None
    for code in AREA_CODES:
        if d.startswith(code):
            ac = code
            break
    if not ac:
        if len(d) == 10 and d.startswith(("03","06")):
            return f"{d[:2]}-{d[2:6]}-{d[6:]}"
        if len(d) == 10:
            return f"{d[:3]}-{d[3:6]}-{d[6:]}"
        return d
    local = d[len(ac):]
    if len(d) == 10:
        if len(ac) == 2:
            return f"{ac}-{local[:4]}-{local[4:]}"
        elif len(ac) == 3:
            return f"{ac}-{local[:3]}-{local[3:]}"
        elif len(ac) == 4:
            return f"{ac}-{local[:3]}-{local[3:]}"
        elif len(ac) == 5:
            return f"{ac}-{local[:2]}-{local[2:]}"
    return d

def _normalize_one_phone(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    d = _digits(raw)
    if not d:
        return ""
    if (len(d) == 11 and d.startswith(_MOBILE_PREFIXES)) or (len(d) == 10 and d.startswith(("70","80","90"))):
        if len(d) == 10:
            d = "0" + d
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if d.startswith("0120") and len(d) == 10:
        return f"{d[:4]}-{d[4:7]}-{d[7:]}"
    if d.startswith("0800") and len(d) == 11:
        return f"{d[:4]}-{d[4:7]}-{d[7:]}"
    if d.startswith("0570") and len(d) == 10:
        return f"{d[:4]}-{d[4:7]}-{d[7:]}"
    if d.startswith("050") and len(d) == 11:
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if len(d) == 9:
        d = "0" + d
    if len(d) == 10 and d.startswith("0"):
        return _format_by_area(d)
    return d

def _normalize_phone(*nums: str) -> str:
    parts = []
    for raw in nums:
        s = _normalize_one_phone(raw)
        if s:
            parts.append(s)
    seen = set()
    uniq = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return ";".join(uniq)

# ============================================================
# 会社名かな生成まわり（法人格除去部分のみ更新）
# ============================================================

_COMPANY_TYPES = [
    "株式会社","（株）","(株)","㈱",
    "有限会社","(有)","（有）","㈲",
    "合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "ＮＰＯ法人","NPO法人","独立行政法人","特定非営利活動法人","地方独立行政法人","国立研究開発法人",
    "医療法人","医療法人財団","医療法人社団",
    "財団法人","一般財団法人","公益財団法人",
    "社団法人","一般社団法人","公益社団法人","社会保険労務士法人",
    "社会福祉法人","学校法人","公立大学法人","国立大学法人",
    "宗教法人","中間法人","特殊法人","特例民法法人",
    "特定目的会社","特定目的信託",
    "有限責任事業組合","有限責任中間法人","投資事業有限責任組合",
    "LLC","ＬＬＣ","Inc","Inc.","Ｉｎｃ","Ｉｎｃ．",
    "Co","Co.","Ｃｏ","Ｃｏ．","Co., Ltd.","Ｃｏ．， Ｌｔｄ．","Co.,Ltd.","Ｃｏ．，Ｌｔｄ．",
    "Ltd","Ltd.","Ｌｔｄ","Ｌｔｄ．","Corporation","Ｃｏｒｐｏｒａｔｉｏｎ",
    "CO., LTD.","ＣＯ．， ＬＴＤ．","CO.,LTD.","ＣＯ．，ＬＴＤ．",
    "Company","Ｃｏｍｐａｎｙ",
]

_VAR_SEP_CLASS = r"[\s\u3000\-‐─―－()\[\]【】／/・,，.．]*"

def _strip_company_type(name: str) -> str:
    base = (name or "").strip()

    # ---- 1) 直接置換 ----
    for t in _COMPANY_TYPES:
        if t:
            base = base.replace(t, "")

    # ---- 2) 複合パターンを優先除去 ----
    complex_types = [
        "一般社団法人","一般財団法人",
        "公益社団法人","公益財団法人",
        "医療法人社団","医療法人財団",
        "社会福祉法人","社会保険労務士法人",
    ]
    for ct in complex_types:
        pat = re.compile(
            r"".join([re.escape(ch) + _VAR_SEP_CLASS for ch in ct])[:-len(_VAR_SEP_CLASS)],
            flags=re.IGNORECASE
        )
        base = pat.sub("", base)

    # ---- 3) 汎用漢字法人格 ----
    _KANJI_TYPE_PATTERNS = [
        ("一般","社団","法人"),
        ("一般","財団","法人"),
        ("社団","法人"),
        ("財団","法人"),
        ("医療","法人"),
        ("社会","福祉","法人"),
        ("独立","行政","法人"),
        ("地方","独立","行政","法人"),
        ("国立","研究","開発","法人"),
        ("学校","法人"),
        ("宗教","法人"),
    ]
    for segs in _KANJI_TYPE_PATTERNS:
        pat = _VAR_SEP_CLASS.join(map(re.escape, segs))
        base = re.sub(pat, "", base, flags=re.IGNORECASE)

    # ---- 4) 英文法人格 ----
    base = re.sub(
        r'(?i)\b(?:co\.?,?\s*ltd\.?|co\.?|ltd\.?|inc\.?|corp\.?|corporation|company|llc)\b[.,\s　]*',
        '',
        base
    )

    # ---- 5) 「一般」「公益」などが先頭に残った場合 ----
    base = re.sub(r'^(一般|公益)\s*', '', base)

    # ---- 6) 前後ノイズ除去 ----
    base = re.sub(r"^[\s　\-‐ ─―－()\[\]【】／/・,，.．]+", "", base)
    base = re.sub(r"[\s　\- ‐─―－()\[\]【】／/・,，.．]+$", "", base)

    return base.strip()

# ============================================================
# 以下、v2.5.7 と同一（_company_kana, _person_name_kana, convert_eight_csv_text_to_atena_csv_text 等）
# ============================================================

# ……（長いため省略せずに完全出力も可能です。希望しますか？）
