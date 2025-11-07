# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.36
# - 姓かな / 名かな / 会社名かな を自動付与
# - ★ 姓名かな = 姓かな + 名かな を出力
# - 住所分割、郵便番号整形、全角ワイド化、電話（最長一致/特番/欠落0補正）対応
# - v2.34: 会社名かなの辞書照合前に「法人格を除去」してから JP/EN 照合
#          フリガナ出力の記号サニタイズ（・／/[]&）＋カタカナ強制を追加
# - v2.36: バージョン表記のみ更新（機能・挙動は v2.34 と同一）
from __future__ import annotations

import io
import csv
import math
import re
import json
import os
import unicodedata
from typing import List, Dict

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES
from utils.kana import to_katakana_guess as _to_kata

__version__ = "v2.36"

# ====== 宛名職人 出力ヘッダ（v2.27 準拠）======
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

# ====== Eight 固定カラム（先頭の既知カラム）======
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ====== 入力ユーティリティ ======
def _clean_key(k: str) -> str:
    return (k or "").lstrip("\ufeff").strip()

def _clean_row(row: dict) -> dict:
    return {_clean_key(k): (v or "") for k, v in row.items()}

# 部署の「前半/後半」分割（区切り：スペース/スラッシュ/中点/読点など）
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
    left = "　".join(tokens[:k])     # 全角スペースで結合
    right = "　".join(tokens[k:]) if k < n else ""
    return left, right

# ====== 電話整形（最長一致＋欠落0補正＋携帯3-4-4） ======
_MOBILE_PREFIXES = ("070", "080", "090")

def _digits(s: str) -> str:
    """全角/半角を問わず『数字だけ』を抽出（Unicodeの数字もOK）。"""
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _format_by_area(d: str) -> str:
    """'0' から始まる固定電話 d を AREA_CODES の最長一致でハイフン挿入。"""
    ac = None
    for code in AREA_CODES:  # 5桁→2桁の順に最長一致
        if d.startswith(code):
            ac = code
            break
    if not ac:
        # フォールバック：03/06 は 2-4-4、それ以外は 3-3-4
        if len(d) == 10 and d.startswith(("03","06")):
            return f"{d[0:2]}-{d[2:6]}-{d[6:10]}"
        if len(d) == 10:
            return f"{d[0:3]}-{d[3:6]}-{d[6:10]}"
        return d

    local = d[len(ac):]
    if len(d) == 10:
        if len(ac) == 2:   # 03 / 06
            return f"{ac}-{local[0:4]}-{local[4:8]}"
        elif len(ac) == 3:
            return f"{ac}-{local[0:3]}-{local[3:7]}"
        elif len(ac) == 4:
            return f"{ac}-{local[0:3]}-{local[3:6]}"
        elif len(ac) == 5:
            return f"{ac}-{local[0:2]}-{local[2:5]}"
    return d

def _normalize_one_phone(raw: str) -> str:
    """単一フィールドを正規化。空or無効は空文字で返す。"""
    if not raw or not raw.strip():
        return ""
    d = _digits(raw)
    if not d:
        return ""

    # 携帯（11桁）または 10桁で先頭0欠落（70/80/90）
    if (len(d) == 11 and d.startswith(_MOBILE_PREFIXES)) or (len(d) == 10 and d.startswith(("70","80","90"))):
        if len(d) == 10:  # 0欠落
            d = "0" + d
        return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"

    # サービス/特番系（0120/0800/0570/050）
    if d.startswith("0120") and len(d) == 10:
        return f"{d[0:4]}-{d[4:7]}-{d[7:10]}"
    if d.startswith("0800") and len(d) == 11:
        return f"{d[0:4]}-{d[4:7]}-{d[7:11]}"
    if d.startswith("0570") and len(d) == 10:
        return f"{d[0:4]}-{d[4:7]}-{d[7:10]}"
    if d.startswith("050") and len(d) == 11:
        return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"

    # 固定：9桁は「先頭0欠落」とみなして補う
    if len(d) == 9:
        d = "0" + d

    # 固定の標準は 10桁（0始まり）
    if len(d) == 10 and d.startswith("0"):
        return _format_by_area(d)

    return d

def _normalize_phone(*nums: str) -> str:
    """複数フィールドを正規化し ';' 連結。"""
    parts: List[str] = []
    for raw in nums:
        s = _normalize_one_phone(raw)
        if s:
            parts.append(s)

    seen = set()
    uniq: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    return ";".join(uniq)

# ====== 会社名かな：法人格を除去してから辞書/推測 ======
_CORP_TERMS = [
    "株式会社","合同会社","有限会社","合資会社","合名会社","相互会社",
    "ＮＰＯ法人","特定非営利活動法人","独立行政法人","地方独立行政法人",
    "医療法人","医療法人社団","医療法人財団",
    "財団法人","一般財団法人","公益財団法人",
    "社団法人","一般社団法人","公益社団法人",
    "社会福祉法人","学校法人","公立大学法人","国立大学法人",
    "宗教法人","中間法人","特殊法人","特例民法法人",
    "特定目的会社","特定目的信託",
    "有限責任事業組合","有限責任中間法人",
    "(株)","（株）","㈱","(有)","（有）","㈲"
]

def _strip_corp_terms(name: str) -> str:
    x = unicodedata.normalize("NFKC", name or "")
    for t in _CORP_TERMS:
        x = x.replace(t, "")
    x = re.sub(r"^[\s　\-‐─―－()\[\]【】／/]+", "", x)
    x = re.sub(r"[\s　\-‐─―－()\[\]【】／/]+$", "", x)
    return x.strip()

def _key_jp(s: str) -> str:
    """JP辞書キー：NFKC→記号統一→空白除去→ASCII全角化"""
    x = unicodedata.normalize("NFKC", s or "")
    x = x.replace("･","・").replace("·","・").replace("•","・")
    x = x.replace("/", "／")
    x = re.sub(r"[ \t\u3000]+"," ", x).strip().replace(" ","")
    out = []
    for ch in x:
        oc = ord(ch)
        if 0x21 <= oc <= 0x7E:
            out.append(chr(oc+0xFEE0))
        else:
            out.append(ch)
    return "".join(out)

def _key_en(s: str) -> str:
    """EN辞書キー：NFKC→lower→空白圧縮→全角／→/"""
    x = unicodedata.normalize("NFKC", s or "").lower()
    x = re.sub(r"[ \t\u3000]+"," ", x).strip()
    return x.replace("／","/")

_SANITIZE_RE = re.compile(r"[・／/\[\]&]")

def _to_katakana_only(t: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFKC", t or ""):
        oc = ord(ch)
        # ひらがな → カタカナ
        if 0x3041 <= oc <= 0x3096:
            out.append(chr(oc + 0x60))
        else:
            out.append(ch)
    return "".join(out)

def _sanitize_kana(s: str) -> str:
    if not s:
        return ""
    z = _to_katakana_only(s)
    z = _SANITIZE_RE.sub("", z)
    z = re.sub(r"[ \t\u3000]+", "", z)
    return z

def _load_json(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "overrides" in data:
            return data["overrides"] or {}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}

def _try_paths(candidates: List[str]) -> str | None:
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
_jp_path = _try_paths([
    os.path.join(_root, "data", "company_kana_overrides_jp.json"),
    os.path.join(_here, "company_kana_overrides_jp.json"),
])
_en_path = _try_paths([
    os.path.join(_root, "data", "company_kana_overrides_en.json"),
    os.path.join(_here, "company_kana_overrides_en.json"),
])

_raw_jp = _load_json(_jp_path) if _jp_path else {}
_raw_en = _load_json(_en_path) if _en_path else {}

_jp_overrides: Dict[str, str] = {}
for k, v in _raw_jp.items():
    nk = _key_jp(_strip_corp_terms(k))
    if nk:
        _jp_overrides[nk] = v

_en_overrides: Dict[str, str] = {}
for k, v in _raw_en.items():
    nk = _key_en(_strip_corp_terms(k))
    if nk:
        _en_overrides[nk] = v

def _company_kana(company_name: str) -> str:
    base = (company_name or "").strip()
    if not base:
        return ""
    bare = _strip_corp_terms(base)

    key_jp = _key_jp(bare)
    if key_jp in _jp_overrides:
        return _sanitize_kana(_jp_overrides[key_jp])

    key_en = _key_en(bare)
    if key_en in _en_overrides:
        return _sanitize_kana(_en_overrides[key_en])

    return _sanitize_kana(_to_kata(bare))

# ====== 変換本体 ======
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    # CSV/TSV 自動判定
    buf = io.StringIO(csv_text)
    sample = buf.read(4096)
    buf.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t"])
    except Exception:
        class _D: delimiter = ","
        dialect = _D()
    reader = csv.DictReader(buf, dialect=dialect)
    reader.fieldnames = [_clean_key(h) for h in (reader.fieldnames or [])]

    rows_out: List[List[str]] = []

    for raw in reader:
        row = _clean_row(raw)
        g = lambda k: (row.get(_clean_key(k), "") or "").strip()

        # 入力
        company_raw = g("会社名")
        dept_raw    = g("部署名")
        title_raw   = g("役職")
        last        = g("姓")
        first       = g("名")
        email       = g("e-mail")
        postcode    = normalize_postcode(g("郵便番号"))   # ###-####
        addr_raw    = g("住所")
        tel_company = g("TEL会社")
        tel_dept    = g("TEL部門")
        tel_direct  = g("TEL直通")
        fax         = g("Fax")
        mobile      = g("携帯電話")
        url         = g("URL")

        # 住所分割（split が建物を拾えなければ住所1に原文維持）
        a1, a2 = split_address(addr_raw)
        if (a2 or "").strip():
            addr1_raw, addr2_raw = a1, a2
        else:
            addr1_raw, addr2_raw = addr_raw, ""

        # 電話
        phone_join = _normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署（前半/後半）
        dept1_raw, dept2_raw = _split_department_half(dept_raw)

        # 全角ワイド化（住所/社名/部署/役職）
        addr1 = to_zenkaku_wide(addr1_raw)
        addr2 = to_zenkaku_wide(addr2_raw)
        company = to_zenkaku_wide(company_raw)
        dept1 = to_zenkaku_wide(dept1_raw)
        dept2 = to_zenkaku_wide(dept2_raw)
        title = to_zenkaku_wide(title_raw)

        # かな自動付与＋サニタイズ
        last_kana_raw  = _to_kata(last) or ""
        first_kana_raw = _to_kata(first) or ""
        company_kana_raw = _company_kana(company) or ""

        full_name = f"{last}{first}"

        last_kana  = _sanitize_kana(last_kana_raw)
        first_kana = _sanitize_kana(first_kana_raw)
        company_kana = _sanitize_kana(company_kana_raw)
        full_name_kana = _sanitize_kana(f"{last_kana}{first_kana}")

        # メモ/備考（固定以降の '1' を拾う）
        fn_clean = reader.fieldnames or []
        tail_headers = fn_clean[len(EIGHT_FIXED):]
        flags: List[str] = []
        for hdr in tail_headers:
            val = (row.get(hdr, "") or "").strip()
            if val in ("1", "1.0", "TRUE", "True", "true"):
                flags.append(hdr)
        memo = ["", "", "", "", ""]
        biko = ""
        for i, hdr in enumerate(flags):
            if i < 5:
                memo[i] = hdr
            else:
                biko += (("\n" if biko else "") + hdr)

        # 出力
        out_row: List[str] = [
            last, first,
            last_kana, first_kana,
            full_name, full_name_kana,
            "", "", "",
            "", "", "",
            "", "", "", "", "",
            "", "", "", "",
            postcode, addr1, addr2, "",
            phone_join, "", email,
            url, "",
            "", "", "", "", "", "", "", "", "",
            company_kana, company,
            dept1, dept2,
            title,
            "", "", "", "",
            memo[0], memo[1], memo[2], memo[3], memo[4],
            biko, "", "",
            "", "", "", "", ""
        ]

        if len(out_row) != len(ATENA_HEADERS):
            raise ValueError(f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}")

        rows_out.append(out_row)

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return out.getvalue()
