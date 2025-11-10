# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.5.8
# - v2.5.8: 法人格除去の強化
#     * 一般社団法人 / 公益財団法人 等の複合パターン除去を強化
#     * 英文法人格（Co., Ltd., Inc., Corporation, Company, LLCなど）除去精度向上
#     * 「一般」「公益」などの単独残りを削除
#     * 前後の全角スペース・中点などを正規化

from __future__ import annotations
import io
import os
import csv
import json
import math
import re
from typing import List, Dict, Tuple, Any

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES
from utils.kana import to_katakana_guess as _to_kata

__version__ = "v2.5.8"

# ============================================================
# 宛名職人 ヘッダ定義
# ============================================================
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

EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所",
    "TEL会社","TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ============================================================
# 共通ユーティリティ
# ============================================================

def _clean_key(k: str) -> str:
    return (k or "").lstrip("\ufeff").strip()

def _clean_row(row: dict) -> dict:
    return {_clean_key(k): (v or "") for k, v in row.items()}

SEP_PATTERN = re.compile(r"(?:／|/|・|,|、|｜|\||\s)+")

def _split_department_half(s: str) -> tuple[str, str]:
    s = (s or "").strip()
    if not s:
        return "", ""
    tokens = [t for t in SEP_PATTERN.split(s) if t]
    if len(tokens) <= 1:
        return s, ""
    k = math.ceil(len(tokens) / 2)
    return "　".join(tokens[:k]), "　".join(tokens[k:])

def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _normalize_phone(*nums: str) -> str:
    seen = set()
    out = []
    for raw in nums:
        s = _normalize_one_phone(raw)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return ";".join(out)

def _normalize_one_phone(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    d = _digits(raw)
    if not d:
        return ""
    if len(d) == 11 and d.startswith(("070","080","090")):
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if len(d) == 10 and d.startswith(("03","06")):
        return f"{d[:2]}-{d[2:6]}-{d[6:]}"
    if len(d) == 10:
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    return d

# ============================================================
# 会社名かな生成まわり（法人格除去強化）
# ============================================================

_COMPANY_TYPES = [
    "株式会社","（株）","(株)","㈱",
    "有限会社","(有)","（有）","㈲",
    "合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "ＮＰＯ法人","NPO法人","独立行政法人","特定非営利活動法人","地方独立行政法人","国立研究開発法人",
    "医療法人","医療法人財団","医療法人社団",
    "財団法人","一般財団法人","公益財団法人",
    "社団法人","一般社団法人","公益社団法人","社会保険労務士法人",
    "社会福祉法人","学校法人","国立大学法人","公立大学法人",
    "宗教法人","中間法人","特殊法人",
    "特定目的会社","有限責任事業組合","有限責任中間法人",
    "LLC","ＬＬＣ","Inc","Inc.","Ｉｎｃ","Ｉｎｃ．",
    "Co","Co.","Ｃｏ","Ｃｏ．","Co., Ltd.","Ｃｏ．， Ｌｔｄ．","Co.,Ltd.","Ｃｏ．，Ｌｔｄ．",
    "Ltd","Ltd.","Ｌｔｄ","Ｌｔｄ．","Corporation","Ｃｏｒｐｏｒａｔｉｏｎ",
    "CO., LTD.","ＣＯ．， ＬＴＤ．","CO.,LTD.","ＣＯ．，ＬＴＤ．",
    "Company","Ｃｏｍｐａｎｙ",
]
_VAR_SEP_CLASS = r"[\s\u3000\-‐─―－()\[\]【】／/・,，.．]*"

def _strip_company_type(name: str) -> str:
    base = (name or "").strip()

    for t in _COMPANY_TYPES:
        if t:
            base = base.replace(t, "")

    complex_types = [
        "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
        "医療法人社団","医療法人財団","社会福祉法人","社会保険労務士法人",
    ]
    for ct in complex_types:
        pat = re.compile(
            r"".join([re.escape(ch) + _VAR_SEP_CLASS for ch in ct])[:-len(_VAR_SEP_CLASS)],
            flags=re.IGNORECASE
        )
        base = pat.sub("", base)

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

    base = re.sub(
        r'(?i)\b(?:co\.?,?\s*ltd\.?|co\.?|ltd\.?|inc\.?|corp\.?|corporation|company|llc)\b[.,\s　]*',
        '',
        base
    )
    base = re.sub(r'^(一般|公益)\s*', '', base)
    base = re.sub(r"^[\s　\-‐ ─―－()\[\]【】／/・,，.．]+", "", base)
    base = re.sub(r"[\s　\- ‐─―－()\[\]【】／/・,，.．]+$", "", base)
    return base.strip()

# ============================================================
# 会社名かな推定
# ============================================================

def _company_kana(name: str) -> str:
    stripped = _strip_company_type(name)
    kana = _to_kata(stripped)
    return kana

# ============================================================
# 人名かな推定
# ============================================================

def _person_name_kana(family: str, given: str) -> Tuple[str, str]:
    return _to_kata(family), _to_kata(given)

# ============================================================
# メイン変換関数
# ============================================================

def convert_eight_csv_text_to_atena_csv_text(text: str) -> str:
    lines = text.strip().splitlines()
    dialect = csv.Sniffer().sniff(lines[0]) if len(lines) > 1 else csv.excel
    reader = csv.DictReader(lines, dialect=dialect)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(ATENA_HEADERS)

    for row in reader:
        row = _clean_row(row)
        company = to_zenkaku_wide(row.get("会社名",""))
        postal = normalize_postcode(row.get("郵便番号",""))
        addr = to_zenkaku_wide(row.get("住所",""))
        addr1, addr2, addr3 = split_address(addr)
        dep1, dep2 = _split_department_half(row.get("部署名",""))
        phone = _normalize_phone(row.get("TEL会社",""), row.get("TEL部門",""), row.get("TEL直通",""))
        email = row.get("e-mail","")
        family, given = row.get("姓",""), row.get("名","")
        family_kana, given_kana = _person_name_kana(family, given)
        company_kana = _company_kana(company)

        rec = [
            family,given,family_kana,given_kana,
            family+given,family_kana+given_kana,"","","",
            "","","","", # 宛先、自宅
            "","","","","","", # 自宅情報
            postal,addr1,addr2,addr3,phone,"",email,row.get("URL",""),"",
            "","","","","","","","",
            company_kana,company,dep1,dep2,row.get("役職",""),
            "","","","", # 連名
            "","","","","","",
            "","","","","","","","",
        ]
        writer.writerow(rec)

    return out.getvalue()

# ============================================================
# デバッグ・バージョン情報
# ============================================================

def get_company_override_versions():
    try:
        with open("data/company_kana_overrides_jp.json","r",encoding="utf-8") as f:
            jp = json.load(f).get("version","?")
    except Exception:
        jp = None
    try:
        with open("data/company_kana_overrides_en.json","r",encoding="utf-8") as f:
            en = json.load(f).get("version","?")
    except Exception:
        en = None
    return jp, en

def get_person_dict_versions():
    return "v1.0.0","v1.0.1","v1.0.1"

def get_area_codes_version():
    return "v1.0.0"

def debug_company_kana(name: str) -> dict:
    stripped = _strip_company_type(name)
    kana = _company_kana(name)
    return {
        "input": name,
        "stripped": stripped,
        "kana": kana,
        "ok": True
    }
