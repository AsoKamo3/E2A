# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.35
# - 宛名職人の完全ヘッダ維持
# - 住所分割: converters.address.split_address を使用
# - 郵便番号 ###-#### / 電話 最長一致＋特番＋0補正
# - かなは必ずカタカナに統一
# - 会社名かな：日本語用/英字用の2辞書で上書き（JP優先→EN）
# - 人名かな：フルネーム辞書を最優先→姓/名トークン辞書→推測（pykakasi）
# - 新規: 各JSON辞書とエリア局番のバージョン取得アクセサを公開

from __future__ import annotations

import io
import os
import csv
import math
import json
import re
from typing import List, Tuple, Dict, Any

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES, __version__ as _AREA_CODES_VER
from utils.kana import to_katakana_guess as _to_kata

__version__ = "v2.35"

# ====== 宛名職人ヘッダ ======
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

# Eight固定ヘッダ（先頭想定）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ====== ユーティリティ ======
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
    left = "　".join(tokens[:k])     # 全角スペースで結合
    right = "　".join(tokens[k:]) if k < n else ""
    return left, right

# ====== 電話整形（最長一致＋欠落0補正＋携帯3-4-4） ======
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
            return f"{d[0:2]}-{d[2:6]}-{d[6:10]}"
        if len(d) == 10:
            return f"{d[0:3]}-{d[3:6]}-{d[6:10]}"
        return d
    local = d[len(ac):]
    if len(d) == 10:
        if len(ac) == 2:
            return f"{ac}-{local[0:4]}-{local[4:8]}"
        elif len(ac) == 3:
            return f"{ac}-{local[0:3]}-{local[3:7]}"
        elif len(ac) == 4:
            return f"{ac}-{local[0:3]}-{local[3:6]}"
        elif len(ac) == 5:
            return f"{ac}-{local[0:2]}-{local[2:5]}"
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
        return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"
    if d.startswith("0120") and len(d) == 10:
        return f"{d[0:4]}-{d[4:7]}-{d[7:10]}"
    if d.startswith("0800") and len(d) == 11:
        return f"{d[0:4]}-{d[4:7]}-{d[7:11]}"
    if d.startswith("0570") and len(d) == 10:
        return f"{d[0:4]}-{d[4:7]}-{d[7:10]}"
    if d.startswith("050") and len(d) == 11:
        return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"
    if len(d) == 9:
        d = "0" + d
    if len(d) == 10 and d.startswith("0"):
        return _format_by_area(d)
    return d

def _normalize_phone(*nums: str) -> str:
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

# ====== 文字正規化（辞書キー用） ======
def _nfkc(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", s or "")

def _collapse_ws(s: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", (s or "").strip())

def _fullwidth_ascii(s: str) -> str:
    out = []
    for ch in s or "":
        oc = ord(ch)
        if ch == " ":
            out.append("\u3000")
        elif 0x21 <= oc <= 0x7E:
            out.append(chr(oc + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)

def _unify_middle_dot(s: str) -> str:
    return (s or "").replace("･", "・").replace("·", "・").replace("•", "・").replace("･", "・")

def _unify_slash(s: str, to: str) -> str:
    return (s or "").replace("／", to).replace("/", to)

def _normalize_company_key_jp(s: str) -> str:
    x = _nfkc(s)
    x = _unify_middle_dot(x)
    x = _unify_slash(x, "／")
    x = _collapse_ws(x)
    x = x.replace(" ", "")  # JPは最終的にスペース除去でガチ一致
    x = _fullwidth_ascii(x) # 全角英数に統一（JP辞書は全角混在前提）
    return x

def _normalize_company_key_en(s: str) -> str:
    x = _nfkc(s).lower()
    x = _collapse_ws(x)
    x = _unify_slash(x, "/")
    x = x.replace("&", "&")
    return x

def _normalize_person_full_key(s: str) -> str:
    x = _nfkc(s)
    x = _collapse_ws(x)
    x = _unify_middle_dot(x)
    x = _fullwidth_ascii(x)
    x = x.replace(" ", "")
    return x

# ====== JSON ローダ ======
def _load_json_dict(path_candidates: List[str], key: str) -> Tuple[Dict[str, str], Dict[str, Any], str | None]:
    for p in path_candidates:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ov = data.get(key) if isinstance(data, dict) else None
                if isinstance(ov, dict):
                    return ov, (data.get("normalize") or {}), (data.get("version") or None)
        except Exception:
            continue
    return {}, {}, None

def _data_path(*names: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, "data", *names)

# 会社辞書（JP / EN）
_COMP_OVR_JP, _COMP_NORM_JP, _COMP_VER_JP = _load_json_dict(
    [_data_path("company_kana_overrides_jp.json")],
    key="overrides"
)
_COMP_OVR_EN, _COMP_NORM_EN, _COMP_VER_EN = _load_json_dict(
    [_data_path("company_kana_overrides_en.json")],
    key="overrides"
)

# 人名辞書（フルネーム最優先）
_PERSON_FULL_OVR, _PERSON_FULL_NORM, _PERSON_FULL_VER = _load_json_dict(
    [_data_path("person_kana_overrides_full.json")],
    key="overrides"
)
# 姓/名トークン辞書
_SURNAME_TERMS, _SURNAME_NORM, _SURNAME_VER = _load_json_dict(
    [_data_path("surname_kana_terms.json")],
    key="terms"
)
_GIVEN_TERMS, _GIVEN_NORM, _GIVEN_VER = _load_json_dict(
    [_data_path("given_kana_terms.json")],
    key="terms"
)

# ====== 会社種別（削除用） ======
_COMPANY_TYPES = [
    "株式会社","（株）","(株)","㈱",
    "有限会社","(有)","（有）","㈲",
    "合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","NPO法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]

def _strip_company_type(s: str) -> str:
    base = (s or "").strip()
    for t in _COMPANY_TYPES:
        base = base.replace(t, "")
    base = re.sub(r"^[\s　\-‐─―－()\[\]【】]+", "", base)
    base = re.sub(r"[\s　\-‐─―－()\[\]【】]+$", "", base)
    return base

def _force_katakana(s: str) -> str:
    if not s:
        return ""
    out = []
    for ch in s:
        oc = ord(ch)
        if 0x3041 <= oc <= 0x3096:  # ぁ〜ゖ
            out.append(chr(oc + 0x60))
        else:
            out.append(ch)
    return "".join(out)

# ====== 会社名かな決定 ======
def _company_kana(company_name: str) -> str:
    raw = (company_name or "").strip()
    if not raw:
        return ""
    key_jp = _normalize_company_key_jp(raw)
    jp_hit = _COMP_OVR_JP.get(key_jp)
    if jp_hit:
        return _force_katakana(jp_hit)
    key_en = _normalize_company_key_en(raw)
    en_hit = _COMP_OVR_EN.get(key_en)
    if en_hit:
        return _force_katakana(en_hit)
    base = _strip_company_type(raw)
    return _force_katakana(_to_kata(base))

# ====== 人名かな決定 ======
def _split_override_full_kana(v: str, last: str, first: str) -> Tuple[str, str]:
    val = (v or "").strip()
    if not val:
        return "", ""
    parts = re.split(r"[\t\u3000 ]+", val)
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        return _force_katakana(parts[0]), _force_katakana(parts[1])
    return (
        _force_katakana(_SURNAME_TERMS.get(last, _to_kata(last))),
        _force_katakana(_GIVEN_TERMS.get(first, _to_kata(first))),
    )

def _person_kana(last: str, first: str) -> Tuple[str, str]:
    full_key = _normalize_person_full_key(f"{last}{first}")
    full_hit = _PERSON_FULL_OVR.get(full_key)
    if full_hit:
        return _split_override_full_kana(full_hit, last, first)
    last_k = _force_katakana(_SURNAME_TERMS.get(last, _to_kata(last)))
    first_k = _force_katakana(_GIVEN_TERMS.get(first, _to_kata(first)))
    return last_k, first_k

# ====== 本体 ======
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
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

        company_raw = g("会社名")
        dept_raw    = g("部署名")
        title_raw   = g("役職")
        last        = g("姓")
        first       = g("名")
        email       = g("e-mail")
        postcode    = normalize_postcode(g("郵便番号"))
        addr_raw    = g("住所")
        tel_company = g("TEL会社")
        tel_dept    = g("TEL部門")
        tel_direct  = g("TEL直通")
        fax         = g("Fax")
        mobile      = g("携帯電話")
        url         = g("URL")

        a1, a2 = split_address(addr_raw)
        if (a2 or "").strip():
            addr1_raw, addr2_raw = a1, a2
        else:
            addr1_raw, addr2_raw = addr_raw, ""

        phone_join = _normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)
        dept1_raw, dept2_raw = _split_department_half(dept_raw)

        addr1 = to_zenkaku_wide(addr1_raw)
        addr2 = to_zenkaku_wide(addr2_raw)
        company = to_zenkaku_wide(company_raw)
        dept1 = to_zenkaku_wide(dept1_raw)
        dept2 = to_zenkaku_wide(dept2_raw)
        title = to_zenkaku_wide(title_raw)

        last_kana, first_kana = _person_kana(last, first)
        company_kana = _company_kana(company)

        full_name = f"{last}{first}"
        full_name_kana = f"{last_kana}{first_kana}"

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

# ====== 版数アクセサ（app から参照） ======
def get_company_override_versions() -> tuple[str|None, str|None]:
    """(JP版, EN版)"""
    return _COMP_VER_JP, _COMP_VER_EN

def get_person_dict_versions() -> tuple[str|None, str|None, str|None]:
    """(フルネーム, 姓, 名)"""
    return _PERSON_FULL_VER, _SURNAME_VER, _GIVEN_VER

def get_area_codes_version() -> str | None:
    return _AREA_CODES_VER
