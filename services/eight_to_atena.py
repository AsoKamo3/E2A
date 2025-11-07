# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.39
# - 姓かな / 名かな / 会社名かな を自動付与（カタカナ強制）
# - ★ 姓名かな = 姓かな + 名かな を出力
# - 住所分割、郵便番号整形、全角ワイド化、電話（最長一致/特番/欠落0補正）対応
# - 会社名かな辞書（JP/EN：フル一致 / 部分トークン合成）・人名辞書（フル/姓/名）対応
# - app.py のバージョン表示用ユーティリティ（辞書/エリア局番）関数を末尾に追加

from __future__ import annotations

import io
import os
import json
import csv
import math
import re
import unicodedata
from typing import List, Tuple, Dict, Any

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES
from utils.kana import to_katakana_guess as _to_kata

__version__ = "v2.39"

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

# ========== クリーニング ==========
def _clean_key(k: str) -> str:
    return (k or "").lstrip("\ufeff").strip()

def _clean_row(row: dict) -> dict:
    return {_clean_key(k): (v or "") for k, v in row.items()}

# 部署の「前半/後半」
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

# ========== 電話整形 ==========
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

# ========== かな生成（会社名・人名） ==========
_KANA_SYMBOLS_RE = re.compile(r"[・／/［\[\]］\]&]+")
def _clean_kana_symbols(s: str) -> str:
    return _KANA_SYMBOLS_RE.sub("", s or "").strip()

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

def _strip_company_type(name: str) -> str:
    base = (name or "").strip()
    for t in _COMPANY_TYPES:
        base = base.replace(t, "")
    base = re.sub(r"^[\s　\-‐─―－()\[\]【】／/・]+", "", base)
    base = re.sub(r"[\s　\-‐─―－()\[\]【】／/・]+$", "", base)
    return base

def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")

def _to_fullwidth_ascii(s: str) -> str:
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

def _normalize_for_jp_cfg(s: str, cfg: Dict[str, Any]) -> str:
    x = s or ""
    if cfg.get("nfkc"): x = _nfkc(x)
    if cfg.get("strip_spaces"): x = x.strip()
    if cfg.get("collapse_spaces"): x = re.sub(r"[ \t\u3000]+", " ", x)
    if cfg.get("unify_middle_dot"): x = x.replace("・", "・")
    if cfg.get("unify_slash_to"): x = x.replace("/", cfg["unify_slash_to"]).replace("／", cfg["unify_slash_to"])
    if cfg.get("fullwidth_ascii"): x = _to_fullwidth_ascii(x)
    return x

def _normalize_for_en_cfg(s: str, cfg: Dict[str, Any]) -> str:
    x = s or ""
    if cfg.get("nfkc"): x = _nfkc(x)
    if cfg.get("lower"): x = x.lower()
    if cfg.get("strip_spaces"): x = x.strip()
    if cfg.get("collapse_spaces"): x = re.sub(r"\s+", " ", x)
    if cfg.get("unify_ampersand"): x = x.replace("&", "&")
    if cfg.get("unify_slash_to"): x = x.replace("\\", "/").replace("／", "/")
    return x

def _load_json(path: str) -> Any | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _data_path(*rel: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, *rel)

def _load_company_overrides() -> tuple[Dict[str, str], Dict[str, str], Dict[str, Any], Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    jp_obj = _load_json(_data_path("data", "company_kana_overrides_jp.json")) or {}
    en_obj = _load_json(_data_path("data", "company_kana_overrides_en.json")) or {}
    tok_obj = _load_json(_data_path("data", "company_overrides_tokens_en.json")) or {}

    jp_norm = jp_obj.get("normalize") or {}
    en_norm = en_obj.get("normalize") or {}
    tok_norm = tok_obj.get("normalize") or {}

    jp_ovr = jp_obj.get("overrides") or {}
    en_ovr = en_obj.get("overrides") or {}
    tok_ovr = tok_obj.get("overrides") or {}

    jp_index: Dict[str, str] = { _normalize_for_jp_cfg(k, jp_norm): v for k, v in jp_ovr.items() }
    en_index: Dict[str, str] = { _normalize_for_en_cfg(k, en_norm): v for k, v in en_ovr.items() }
    tok_index: Dict[str, str] = { _normalize_for_en_cfg(k, tok_norm): v for k, v in tok_ovr.items() }
    return jp_index, en_index, jp_norm, en_norm, tok_index, tok_norm

def _load_person_dicts() -> tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    full = _load_json(_data_path("data", "person_full_overrides.json")) or {}
    surname = _load_json(_data_path("data", "surname_kana_terms.json")) or {}
    given = _load_json(_data_path("data", "given_kana_terms.json")) or {}

    def pick_terms(obj: Dict[str, Any]) -> Dict[str, str]:
        if isinstance(obj, dict):
            t = obj.get("terms")
            if isinstance(t, dict):
                return {str(k): str(v) for k, v in t.items()}
        return {}
    return pick_terms(full), pick_terms(surname), pick_terms(given)

# --- 部分一致合成（最長一致→前から確定、無音区切り無視） ---
_SEP_DROP = re.compile(r"[／/＆&・\s\u3000]+")

def _compose_kana_from_tokens(src_stripped: str,
                              en_tok_index: Dict[str, str],
                              en_tok_norm: Dict[str, Any],
                              min_len: int) -> str:
    """
    ENトークン辞書で部分一致合成。
    - 区切り（／ / ＆ ・ 空白）は読み上げず無視
    - 辞書ヒット→その読み
    - ノーヒットの連続英字は _to_kata でカタカナ化
    - その他文字はそのまま無視（ここではEN特化）
    """
    # 区切りはスペース化→除去（位置合わせ単純化）
    norm_base = _normalize_for_en_cfg(src_stripped, {"nfkc": True, "lower": True, "strip_spaces": True, "collapse_spaces": True, "unify_slash_to": "/"})
    work = _SEP_DROP.sub("", norm_base)
    i = 0
    out: List[str] = []
    n = len(work)

    # 長いトークン優先で探索
    tok_keys = sorted(en_tok_index.keys(), key=len, reverse=True)

    while i < n:
        hit = False
        # 長語優先スキャン
        for tk in tok_keys:
            if len(tk) < max(1, min_len):
                continue
            if work.startswith(tk, i):
                out.append(en_tok_index[tk])
                i += len(tk)
                hit = True
                break
        if hit:
            continue

        ch = work[i]
        # 英字連続をまとめて _to_kata
        if "a" <= ch <= "z":
            j = i + 1
            while j < n and "a" <= work[j] <= "z":
                j += 1
            frag = work[i:j]
            out.append(_to_kata(frag))
            i = j
        else:
            # EN処理対象外（数字/記号）は読み生成に寄与しない（スキップ）
            i += 1

    return "".join(out)

# --- 会社名かな ---
def _company_kana(company_name: str,
                  jp_index: Dict[str, str], en_index: Dict[str, str],
                  jp_norm: Dict[str, Any], en_norm: Dict[str, Any],
                  en_tok_index: Dict[str, str], en_tok_norm: Dict[str, Any],
                  token_min_len: int, acronym_charwise: bool) -> str:
    base = (company_name or "").strip()
    if not base:
        return ""

    stripped = _strip_company_type(base)

    # 1) JPフル一致
    jp_key = _normalize_for_jp_cfg(stripped, jp_norm)
    if jp_key in jp_index:
        return _clean_kana_symbols(jp_index[jp_key])

    # 2) ENフル一致
    en_key = _normalize_for_en_cfg(stripped, en_norm)
    if en_key in en_index:
        return _clean_kana_symbols(en_index[en_key])

    # 2.5) 部分一致合成（環境変数で制御）
    use_partial = (os.environ.get("COMPANY_PARTIAL_OVERRIDES", "0") == "1")
    if use_partial:
        min_len = int(os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN", "2") or "2")
        min_len = max(1, min_len)
        composed = _compose_kana_from_tokens(stripped, en_tok_index, en_tok_norm, min_len)
        if composed.strip():
            return _clean_kana_symbols(composed)

    # 3) 英字略語を1文字ずつ読む（環境変数で制御）
    if acronym_charwise and re.fullmatch(r"[A-Za-z\s/&／・\u3000]+", stripped or ""):
        letters = re.sub(r"[^A-Za-z]", "", stripped or "")
        if letters:
            return _clean_kana_symbols(_to_kata(letters))

    # 4) 推測
    return _clean_kana_symbols(_to_kata(stripped))

# --- 人名かな ---
def _person_name_kana(last: str, first: str,
                      full_over: Dict[str, str],
                      surname_terms: Dict[str, str],
                      given_terms: Dict[str, str]) -> tuple[str, str, str]:
    last = (last or "").strip()
    first = (first or "").strip()
    full = f"{last}{first}"
    if full in full_over:
        full_k = _clean_kana_symbols(full_over[full])
        last_k = _clean_kana_symbols(surname_terms.get(last, _to_kata(last)))
        first_k = _clean_kana_symbols(given_terms.get(first, _to_kata(first)))
        return last_k, first_k, full_k
    last_k = _clean_kana_symbols(surname_terms.get(last, _to_kata(last)))
    first_k = _clean_kana_symbols(given_terms.get(first, _to_kata(first)))
    full_k = f"{last_k}{first_k}"
    return last_k, first_k, full_k

# ========== 本体：Eight→宛名職人 ==========
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    buf = io.StringIO(csv_text)
    sample = buf.read(4096); buf.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t"])
    except Exception:
        class _D: delimiter = ","
        dialect = _D()
    reader = csv.DictReader(buf, dialect=dialect)
    reader.fieldnames = [_clean_key(h) for h in (reader.fieldnames or [])]

    # 辞書ロード
    JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, EN_TOK_INDEX, EN_TOK_CFG = _load_company_overrides()
    FULL_OVER, SURNAME_TERMS, GIVEN_TERMS = _load_person_dicts()

    # 環境フラグ
    acronym_charwise = (os.environ.get("PARTIAL_ACRONYM_CHARWISE", "0") == "1")

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

        # 住所
        a1, a2 = split_address(addr_raw)
        if (a2 or "").strip():
            addr1_raw, addr2_raw = a1, a2
        else:
            addr1_raw, addr2_raw = addr_raw, ""

        # 電話
        phone_join = _normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署
        dept1_raw, dept2_raw = _split_department_half(dept_raw)

        # 全角ワイド化
        addr1 = to_zenkaku_wide(addr1_raw)
        addr2 = to_zenkaku_wide(addr2_raw)
        company = to_zenkaku_wide(company_raw)
        dept1 = to_zenkaku_wide(dept1_raw)
        dept2 = to_zenkaku_wide(dept2_raw)
        title = to_zenkaku_wide(title_raw)

        # かな
        company_kana = _company_kana(
            company, JP_INDEX, EN_INDEX, JP_CFG, EN_CFG,
            EN_TOK_INDEX, EN_TOK_CFG,
            int(os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN", "2") or "2"),
            acronym_charwise
        ) or ""
        last_kana, first_kana, full_name_kana = _person_name_kana(last, first, FULL_OVER, SURNAME_TERMS, GIVEN_TERMS)
        full_name = f"{last}{first}"

        # メモ/備考（固定以降 '1'）
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

# ==== version reporting ====
def _read_json_version(*relative_candidate_paths: str) -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    for rel in relative_candidate_paths:
        path = os.path.join(root, rel)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    v = data.get("version")
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        except Exception:
            continue
    return None

def get_company_override_versions() -> tuple[str | None, str | None]:
    jp_ver = _read_json_version(
        os.path.join("data", "company_kana_overrides_jp.json"),
        os.path.join("services", "data", "company_kana_overrides_jp.json"),
    )
    en_ver = _read_json_version(
        os.path.join("data", "company_kana_overrides_en.json"),
        os.path.join("services", "data", "company_kana_overrides_en.json"),
    )
    return jp_ver, en_ver

def get_person_dict_versions() -> tuple[str | None, str | None, str | None]:
    full_ver = _read_json_version(
        os.path.join("data", "person_full_overrides.json"),
        os.path.join("services", "data", "person_full_overrides.json"),
    )
    surname_ver = _read_json_version(
        os.path.join("data", "surname_kana_terms.json"),
        os.path.join("services", "data", "surname_kana_terms.json"),
    )
    given_ver = _read_json_version(
        os.path.join("data", "given_kana_terms.json"),
        os.path.join("services", "data", "given_kana_terms.json"),
    )
    return full_ver, surname_ver, given_ver

def get_area_codes_version() -> str | None:
    try:
        from utils.jp_area_codes import __version__ as AREAC_VER
        return AREAC_VER
    except Exception:
        return None
