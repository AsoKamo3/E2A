# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.45
# - 既存ロジックは維持
# - app.py の /selftest/company_kana 用に debug_company_kana(name) を提供

from __future__ import annotations

import io
import os
import json
import csv
import math
import re
from typing import List, Tuple, Dict, Any

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES
from utils.kana import to_katakana_guess as _to_kata

__version__ = "v2.45"

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

# Eight 固定ヘッダ（ここまでが固定、それ以降は可変のカスタム列）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ========== クリーニング系ユーティリティ ==========
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

# ========== 電話整形（最長一致＋欠落0補正＋携帯3-4-4） ==========
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
    # 汎用ルール（局番長に応じた分割）
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

    # 固定：9桁は「先頭0欠落」とみなして補う（例: 3-5724-8523 → 03-5724-8523）
    if len(d) == 9:
        d = "0" + d

    # 固定の標準は 10桁（0始まり）。最長一致で体裁。
    if len(d) == 10 and d.startswith("0"):
        return _format_by_area(d)

    # それ以外（桁不明など）は安全側で元数字のまま
    return d

def _normalize_phone(*nums: str) -> str:
    """
    引数の電話フィールド群を正規化し、空でないものを ';' 連結。
    - 前後空白/全角ダッシュ混在/重複除去に対応
    """
    parts: List[str] = []
    for raw in nums:
        s = _normalize_one_phone(raw)
        if s:
            parts.append(s)

    # 重複除去（順序維持）
    seen = set()
    uniq: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    return ";".join(uniq)

# ========== かな生成：会社名・人名（辞書→推測） ==========
# 記号類はフリガナから除去
_KANA_SYMBOLS_RE = re.compile(r"[・／/［\[\]］\]&]+")
def _clean_kana_symbols(s: str) -> str:
    return _KANA_SYMBOLS_RE.sub("", s or "").strip()

# 法人格（会社種別）除去の簡易表（辞書マッチ前に除去）
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
    # 前後ノイズ記号を軽く除去
    base = re.sub(r"^[\s　\-‐─―－()\[\]【】／/・]+", "", base)
    base = re.sub(r"[\s　\-‐─―－()\[\]【】／/・]+$", "", base)
    return base

# ---- 会社名かな辞書（JP/EN）ローダ ----
def _load_json(path: str) -> Any | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _data_path(*rel: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))       # services/
    root = os.path.dirname(here)                             # repo root
    return os.path.join(root, *rel)

def _normalize_for_jp_cfg(s: str, cfg: Dict[str, Any]) -> str:
    x = s or ""
    # NFKC
    try:
        import unicodedata
        x = unicodedata.normalize("NFKC", x)
    except Exception:
        pass
    # trim / collapse
    if cfg.get("strip_spaces"):
        x = x.strip()
    if cfg.get("collapse_spaces"):
        x = re.sub(r"[ \t\u3000]+", " ", x)
    # 記号統一
    if cfg.get("unify_middle_dot"):
        x = x.replace("・", "・")
    if cfg.get("unify_slash_to"):
        x = x.replace("/", cfg["unify_slash_to"]).replace("／", cfg["unify_slash_to"])
    # ASCII を全角へ
    if cfg.get("fullwidth_ascii"):
        out = []
        for ch in x:
            oc = ord(ch)
            if ch == " ":
                out.append("\u3000")
            elif 0x21 <= oc <= 0x7E:
                out.append(chr(oc + 0xFEE0))
            else:
                out.append(ch)
        x = "".join(out)
    return x

def _normalize_for_en_cfg(s: str, cfg: Dict[str, Any]) -> str:
    x = s or ""
    # NFKC
    try:
        import unicodedata
        x = unicodedata.normalize("NFKC", x)
    except Exception:
        pass
    if cfg.get("lower"):
        x = x.lower()
    if cfg.get("strip_spaces"):
        x = x.strip()
    if cfg.get("collapse_spaces"):
        x = re.sub(r"\s+", " ", x)
    if cfg.get("unify_slash_to"):
        x = x.replace("\\", "/").replace("／", "/")
    return x

def _load_company_overrides() -> tuple[
    Dict[str, str], Dict[str, str], Dict[str, Any], Dict[str, Any], Dict[str, str], Dict[str, str]
]:
    # JP/EN JSON を読む（埋め込み tokens もここで抽出）
    jp_obj = _load_json(_data_path("data", "company_kana_overrides_jp.json")) or {}
    en_obj = _load_json(_data_path("data", "company_kana_overrides_en.json")) or {}

    jp_norm = jp_obj.get("normalize") or {}
    en_norm = en_obj.get("normalize") or {}

    jp_ovr = jp_obj.get("overrides") or {}
    en_ovr = en_obj.get("overrides") or {}

    jp_tok = jp_obj.get("tokens") or {}
    en_tok = en_obj.get("tokens") or {}

    # 正規化後キーで引けるように再構成
    jp_index: Dict[str, str] = {_normalize_for_jp_cfg(k, jp_norm): v for k, v in jp_ovr.items()}
    en_index: Dict[str, str] = {_normalize_for_en_cfg(k, en_norm): v for k, v in en_ovr.items()}

    jp_tokens: Dict[str, str] = {_normalize_for_jp_cfg(k, jp_norm): v for k, v in jp_tok.items()}
    en_tokens: Dict[str, str] = {_normalize_for_en_cfg(k, en_norm): v for k, v in en_tok.items()}

    return jp_index, en_index, jp_norm, en_norm, jp_tokens, en_tokens

# ---- 人名辞書（フル/姓/名）ローダ ----
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

# ---- 会社名かな生成（辞書→部分一致（可）→推測） ----
def _company_kana(company_name: str,
                  jp_index: Dict[str, str], en_index: Dict[str, str],
                  jp_norm: Dict[str, Any], en_norm: Dict[str, Any],
                  jp_tokens: Dict[str, str] | None = None, en_tokens: Dict[str, str] | None = None) -> str:
    base = (company_name or "").strip()
    if not base:
        return ""

    # 法人格を除去
    stripped = _strip_company_type(base)

    # 1) フル一致（JP/EN）
    jp_key = _normalize_for_jp_cfg(stripped, jp_norm)
    if jp_key in jp_index:
        return _clean_kana_symbols(jp_index[jp_key])

    en_key = _normalize_for_en_cfg(stripped, en_norm)
    if en_key in en_index:
        return _clean_kana_symbols(en_index[en_key])

    # 2) 部分一致（オプション）
    if os.environ.get("COMPANY_PARTIAL_OVERRIDES", "0") not in ("", "0", "false", "False"):
        token_min = int(os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN", "2") or "2")
        kana_parts: List[str] = []

        # EN tokens
        if en_tokens:
            s = en_key
            # 文字単位アクロニム読み（任意）
            if os.environ.get("PARTIAL_ACRONYM_CHARWISE", "0") not in ("", "0", "false", "False"):
                for ch in s:
                    if ch in en_tokens:
                        kana_parts.append(_clean_kana_symbols(en_tokens[ch]))
            # 単語トークン（長い順）
            toks = sorted(en_tokens.keys(), key=lambda x: (-len(x), x))
            for t in toks:
                if len(t) < token_min:
                    continue
                if t in s:
                    kana_parts.append(_clean_kana_symbols(en_tokens[t]))
                    s = s.replace(t, " ")

        # JP tokens
        if jp_tokens:
            s = jp_key
            toks = sorted(jp_tokens.keys(), key=lambda x: (-len(x), x))
            for t in toks:
                if len(t) < token_min:
                    continue
                if t in s:
                    kana_parts.append(_clean_kana_symbols(jp_tokens[t]))
                    s = s.replace(t, " ")

        if kana_parts:
            return _clean_kana_symbols("".join(kana_parts))

    # 3) 推測（カタカナ強制）
    return _clean_kana_symbols(_to_kata(stripped))

# ---- 人名かな生成（フル最優先→姓/名トークン→推測） ----
def _person_name_kana(last: str, first: str,
                      full_over: Dict[str, str],
                      surname_terms: Dict[str, str],
                      given_terms: Dict[str, str]) -> tuple[str, str, str]:
    last = (last or "").strip()
    first = (first or "").strip()
    full = f"{last}{first}"

    # フルネーム辞書が最優先
    if full in full_over:
        full_k = _clean_kana_symbols(full_over[full])
        # 個別は辞書優先→推測
        last_k = _clean_kana_symbols(surname_terms.get(last, _to_kata(last)))
        first_k = _clean_kana_symbols(given_terms.get(first, _to_kata(first)))
        return last_k, first_k, full_k

    # 姓/名トークン辞書
    last_k = _clean_kana_symbols(surname_terms.get(last, _to_kata(last)))
    first_k = _clean_kana_symbols(given_terms.get(first, _to_kata(first)))

    full_name_kana = f"{last_k}{first_k}"
    return last_k, first_k, full_name_kana

# ========== 本体：Eight→宛名職人 ==========
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

    # 会社/人名辞書ロード
    JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, JP_TOK, EN_TOK = _load_company_overrides()
    FULL_OVER, SURNAME_TERMS, GIVEN_TERMS = _load_person_dicts()

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

        # かな自動付与（会社名: 辞書→推測、人名: フル→姓/名→推測、いずれもカタカナ＆記号除去）
        company_kana = _company_kana(company, JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, JP_TOK, EN_TOK) or ""
        last_kana, first_kana, full_name_kana = _person_name_kana(last, first, FULL_OVER, SURNAME_TERMS, GIVEN_TERMS)

        # ★ 姓名は素の結合（ユーザ仕様）
        full_name = f"{last}{first}"

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

# ==== minimal add-ons for version reporting (do not change existing logic) ====
def _read_json_version(*relative_candidate_paths: str) -> str | None:
    """
    複数の相対候補パスのどれかにある JSON を開き、"version" を返す。
    存在しない/読めない/フォーマット不明のときは None。
    """
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
    """
    app 側のバージョン表示用：会社名かな辞書（JP/EN）の version を返す。
    """
    jp_ver = _read_json_version(
        os.path.join("data", "company_kana_overrides_jp.json"),
        os.path.join("services", "data", "company_kana_overrides_jp.json"),  # 万一の配置違いに弱対応
    )
    en_ver = _read_json_version(
        os.path.join("data", "company_kana_overrides_en.json"),
        os.path.join("services", "data", "company_kana_overrides_en.json"),
    )
    return jp_ver, en_ver

def get_person_dict_versions() -> tuple[str | None, str | None, str | None]:
    """
    app 側のバージョン表示用：人名辞書（フル/姓/名）の version を返す。
    """
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
    """
    app 側のバージョン表示用：エリア局番辞書の __version__ を返す。
    """
    try:
        from utils.jp_area_codes import __version__ as AREAC_VER
        return AREAC_VER
    except Exception:
        return None

# ==== new: debug for company kana ====
def debug_company_kana(name: str) -> Dict[str, Any]:
    """
    会社名かな生成のデバッグ用：
    - JP/EN 正規化キー
    - どちらのトラックを採用したか（full-jp/full-en/partial/guess）
    - 使われたトークン（partial 時）
    - 最終 kana
    """
    JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, JP_TOK, EN_TOK = _load_company_overrides()
    stripped = _strip_company_type(name or "")
    jp_key = _normalize_for_jp_cfg(stripped, JP_CFG)
    en_key = _normalize_for_en_cfg(stripped, EN_CFG)

    route = "guess"
    hits: Dict[str, Any] = {"full": None, "partial": []}
    kana: str | None = None

    # full match
    if jp_key in JP_INDEX:
        route = "full-jp"
        kana = _clean_kana_symbols(JP_INDEX[jp_key])
    elif en_key in EN_INDEX:
        route = "full-en"
        kana = _clean_kana_symbols(EN_INDEX[en_key])

    # partial
    if kana is None and os.environ.get("COMPANY_PARTIAL_OVERRIDES", "0") not in ("", "0", "false", "False"):
        token_min = int(os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN", "2") or "2")
        parts: List[str] = []
        used: List[Tuple[str, str]] = []

        # EN tokens
        s = en_key
        if EN_TOK:
            if os.environ.get("PARTIAL_ACRONYM_CHARWISE", "0") not in ("", "0", "false", "False"):
                for ch in s:
                    if ch in EN_TOK:
                        parts.append(_clean_kana_symbols(EN_TOK[ch])); used.append(("en-char", ch))
            toks = sorted(EN_TOK.keys(), key=lambda x: (-len(x), x))
            for t in toks:
                if len(t) < token_min: continue
                if t in s:
                    parts.append(_clean_kana_symbols(EN_TOK[t])); used.append(("en", t))
                    s = s.replace(t, " ")

        # JP tokens
        s = jp_key
        if JP_TOK:
            toks = sorted(JP_TOK.keys(), key=lambda x: (-len(x), x))
            for t in toks:
                if len(t) < token_min: continue
                if t in s:
                    parts.append(_clean_kana_symbols(JP_TOK[t])); used.append(("jp", t))
                    s = s.replace(t, " ")

        if parts:
            kana = _clean_kana_symbols("".join(parts))
            route = "partial"
            hits["partial"] = used

    # guess
    if kana is None:
        kana = _clean_kana_symbols(_to_kata(stripped))
        route = "guess"

    return {
        "input": name,
        "stripped": stripped,
        "jp_key": jp_key,
        "en_key": en_key,
        "route": route,
        "hits": hits,
        "kana": kana,
    }
