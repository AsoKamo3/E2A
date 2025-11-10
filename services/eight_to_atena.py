# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体 v2.5.5
# - 既存ロジックは維持（v2.5.2 ベース）
# - “部分一致”に左→右の貪欲最長一致スキャナ＋未マッチ区間の推測埋め
# - PARTIAL_ACRONYM_MAX_LEN（既定3）で略称の1文字読み上げを短い塊に限定
# - app.py の /selftest/company_kana 用に debug_company_kana(name) を提供
# - v2.5.1: ENトークン境界判定を ASCII 英数字のみに限定
# - v2.5.2: Kanji 法人格（一般社団法人/一般財団法人など）を可変セパレータ付きで除去
# - v2.5.5:
#     - 法人格一覧を「長い表記優先」で置換（一般社団法人 の「一般」残りを防止）
#     - カナ記号除去に丸括弧を追加（（個人事業主）などを無音化）

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

__version__ = "v2.5.5"

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

    # 固定：9桁は「先頭0欠落」とみなして補う
    if len(d) == 9:
        d = "0" + d

    # 固定の標準は 10桁（0始まり）
    if len(d) == 10 and d.startswith("0"):
        return _format_by_area(d)

    # それ以外（桁不明など）は安全側で元数字のまま
    return d

def _normalize_phone(*nums: str) -> str:
    """
    引数の電話フィールド群を正規化し、空でないものを ';' 連結。
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
# 記号類はフリガナから除去（丸括弧も無音扱いにする）
_KANA_SYMBOLS_RE = re.compile(r"[・／/［\[\]］&\(\)（）]+")
def _clean_kana_symbols(s: str) -> str:
    return _KANA_SYMBOLS_RE.sub("", s or "").strip()

# 法人格（会社種別）除去の簡易表（辞書マッチ前に除去）
_COMPANY_TYPES = [
    "株式会社","（株）","(株)","㈱",
    "有限会社","(有)","（有）","㈲",
    "合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "ＮＰＯ法人","NPO法人","独立行政法人","特定非営利活動法人","地方独立行政法人","国立研究開発法人",
    "医療法人社団","医療法人財団","医療法人",  # 長い順優先で扱う
    "財団法人","一般財団法人","公益財団法人",
    "社団法人","一般社団法人","公益社団法人","社会保険労務士法人",
    "社会福祉法人","学校法人","公立大学法人","国立大学法人",
    "宗教法人","中間法人","特殊法人","特例民法法人",
    "特定目的会社","特定目的信託",
    "有限責任事業組合","有限責任中間法人","投資事業有限責任組合",
    # 英語系
    "LLC","ＬＬＣ","Inc","Inc.","Ｉｎｃ","Ｉｎｃ．","Co","Co.","Ｃｏ","Ｃｏ．",
    "Co., Ltd.","Ｃｏ．， Ｌｔｄ．","Co.,Ltd.","Ｃｏ．，Ｌｔｄ．",
    "Ltd","Ltd.","Ｌｔｄ","Ｌｔｄ．","Corporation","Ｃｏｒｐｏｒａｔｉｏｎ",
    "CO., LTD.","ＣＯ．， ＬＴＤ．","CO.,LTD.","ＣＯ．，ＬＴＤ．",
    "Company","Ｃｏｍｐａｎｙ",
]

# v2.5.2: 可変セパレータ付きの Kanji 法人格パターン
_KANJI_TYPE_PATTERNS = [
    ("一般","社団","法人"),
    ("一般","財団","法人"),
    ("公益","社団","法人"),
    ("公益","財団","法人"),
    ("社団","法人"),
    ("財団","法人"),
    ("医療","法人","社団"),
    ("医療","法人"),
    ("社会","福祉","法人"),
    ("独立","行政","法人"),
    ("地方","独立","行政","法人"),
    ("国立","研究","開発","法人"),
    ("学校","法人"),
    ("宗教","法人"),
]
_VAR_SEP_CLASS = r"[\s\u3000\-‐─―－()\[\]【】／/・,，.．]*"

def _strip_company_type(name: str) -> str:
    base = (name or "").strip()

    # 1) 固定リスト：長い文字列から順に除去（部分一致の取りこぼし防止）
    for t in sorted(_COMPANY_TYPES, key=len, reverse=True):
        if t:
            base = base.replace(t, "")

    # 2) 可変セパレータ入り Kanji 法人格も除去
    for segs in _KANJI_TYPE_PATTERNS:
        pat = _VAR_SEP_CLASS.join(map(re.escape, segs))
        base = re.sub(pat, "", base)

    # 3) 前後ノイズ記号を軽く除去
    base = re.sub(r"^[\s　\-‐─―－()\[\]【】／/・,，.．]+", "", base)
    base = re.sub(r"[\s　\-‐─―－()\[\]【】／/・,，.．]+$", "", base)
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
    try:
        import unicodedata
        x = unicodedata.normalize("NFKC", x)
    except Exception:
        pass
    if cfg.get("strip_spaces"):
        x = x.strip()
    if cfg.get("collapse_spaces"):
        x = re.sub(r"[ \t\u3000]+", " ", x)
    if cfg.get("unify_middle_dot"):
        x = x.replace("・", "・")
    if cfg.get("unify_slash_to"):
        x = x.replace("/", cfg["unify_slash_to"]).replace("／", cfg["unify_slash_to"])
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

# --- スキャナ用ビュー（長さをほぼ保つ） ---
def _nfkc(s: str) -> str:
    try:
        import unicodedata
        return unicodedata.normalize("NFKC", s or "")
    except Exception:
        return s or ""

def _scan_view_en(s: str) -> str:
    x = _nfkc(s).lower()
    x = x.replace("／", "/").replace("\\", "/")
    return x

def _scan_view_jp(s: str) -> str:
    x = _nfkc(s)
    x = x.replace("/", "／").replace("\\", "／")
    out = []
    for ch in x:
        oc = ord(ch)
        if ch == " ":
            out.append("\u3000")
        elif 0x21 <= oc <= 0x7E:
            out.append(chr(oc + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)

_SEP_CHARS = set(" ／/・,&，,．.")  # 区切りや無音記号

def _is_sep(ch: str) -> bool:
    return ch in _SEP_CHARS or ch.isspace()

# ---- 人名辞書ローダ ----
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

# ---- 会社名かな（JP/EN辞書 → 部分一致 → 推測） ----
def _company_kana(company_name: str,
                  jp_index: Dict[str, str], en_index: Dict[str, str],
                  jp_norm: Dict[str, Any], en_norm: Dict[str, Any],
                  jp_tokens: Dict[str, str] | None = None, en_tokens: Dict[str, str] | None = None) -> str:
    base = (company_name or "").strip()
    if not base:
        return ""

    stripped = _strip_company_type(base)

    # 1) フル一致
    jp_key = _normalize_for_jp_cfg(stripped, jp_norm)
    if jp_key in jp_index:
        return _clean_kana_symbols(jp_index[jp_key])

    en_key = _normalize_for_en_cfg(stripped, en_norm)
    if en_key in en_index:
        return _clean_kana_symbols(en_index[en_key])

    # 2) 部分一致スキャン
    if os.environ.get("COMPANY_PARTIAL_OVERRIDES", "0") not in ("", "0", "false", "False"):
        token_min = int(os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN", "2") or "2")
        allow_charwise = os.environ.get("PARTIAL_ACRONYM_CHARWISE", "0") not in ("", "0", "false", "False")
        acronym_max = int(os.environ.get("PARTIAL_ACRONYM_MAX_LEN", "3") or "3")

        view_en = _scan_view_en(stripped)
        view_jp = _scan_view_jp(stripped)

        en_keys: List[str] = []
        jp_keys: List[str] = []
        if en_tokens:
            en_keys = [k for k in en_tokens.keys() if len(k) >= token_min]
            en_keys.sort(key=lambda x: (-len(x), x))
        if jp_tokens:
            jp_keys = [k for k in jp_tokens.keys() if len(k) >= token_min]
            jp_keys.sort(key=lambda x: (-len(x), x))

        n = len(stripped)
        i = 0
        out_parts: List[str] = []
        gap_buf: List[str] = []

        def flush_gap():
            if not gap_buf:
                return
            seg = "".join(gap_buf)
            gap_buf.clear()
            if seg.strip():
                out_parts.append(_clean_kana_symbols(_to_kata(seg)))

        def _is_ascii_alnum(ch: str) -> bool:
            return ("a" <= ch <= "z") or ("0" <= ch <= "9")

        while i < n:
            ch = stripped[i]

            if _is_sep(ch):
                flush_gap()
                i += 1
                continue

            matched: Optional[Tuple[int, str]] = None

            # JP tokens（長い順）
            if jp_tokens:
                for t in jp_keys:
                    tl = len(t)
                    if tl <= 0 or i + tl > n:
                        continue
                    if view_jp[i:i+tl] == t:
                        matched = (tl, _clean_kana_symbols(jp_tokens[t]))
                        break

            # EN tokens（ASCII 英数字境界）
            if matched is None and en_tokens:
                for t in en_keys:
                    tl = len(t)
                    if tl <= 0 or i + tl > n:
                        continue
                    prev_ok = (i == 0) or not _is_ascii_alnum(view_en[i-1])
                    next_ok = (i + tl == n) or not _is_ascii_alnum(view_en[i+tl])
                    if view_en[i:i+tl] == t and (prev_ok or next_ok):
                        matched = (tl, _clean_kana_symbols(en_tokens[t]))
                        break

            if matched is not None:
                flush_gap()
                tl, kana_piece = matched
                out_parts.append(kana_piece)
                i += tl
                continue

            # 短い英数字塊は charwise（任意）
            if allow_charwise and view_en[i].isalnum():
                j = i
                while j < n and view_en[j].isalnum():
                    j += 1
                run_len = j - i
                if 1 <= run_len <= acronym_max and en_tokens:
                    flush_gap()
                    for k in range(i, j):
                        ch_en = view_en[k]
                        if ch_en in en_tokens:
                            out_parts.append(_clean_kana_symbols(en_tokens[ch_en]))
                        else:
                            gap_buf.append(stripped[k])
                    i = j
                    continue

            # どれにも当たらない → ギャップに貯める
            gap_buf.append(ch)
            i += 1

        flush_gap()

        if out_parts:
            return _clean_kana_symbols("".join(out_parts))

    # 3) 最後の保険：全体を推測
    return _clean_kana_symbols(_to_kata(stripped))

# ---- 人名かな生成 ----
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
    full_name_kana = f"{last_k}{first_k}"
    return last_k, first_k, full_name_kana

# ========== 本体：Eight→宛名職人 ==========
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    buf = io.StringIO(csv_text)
    sample = buf.read(4096)
    buf.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t"])
    except Exception:
        class _D:
            delimiter = ","
        dialect = _D()
    reader = csv.DictReader(buf, dialect=dialect)
    reader.fieldnames = [_clean_key(h) for h in (reader.fieldnames or [])]

    JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, JP_TOK, EN_TOK = _load_company_overrides()
    FULL_OVER, SURNAME_TERMS, GIVEN_TERMS = _load_person_dicts()

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

        company_kana = _company_kana(company, JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, JP_TOK, EN_TOK) or ""
        last_kana, first_kana, full_name_kana = _person_name_kana(last, first, FULL_OVER, SURNAME_TERMS, GIVEN_TERMS)

        full_name = f"{last}{first}"

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
            raise ValueError(
                f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}"
            )

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

# ==== debug for company kana ====
def debug_company_kana(name: str) -> Dict[str, Any]:
    JP_INDEX, EN_INDEX, JP_CFG, EN_CFG, JP_TOK, EN_TOK = _load_company_overrides()
    stripped = _strip_company_type(name or "")
    jp_key = _normalize_for_jp_cfg(stripped, JP_CFG)
    en_key = _normalize_for_en_cfg(stripped, EN_CFG)

    route = None
    kana: Optional[str] = None
    if jp_key in JP_INDEX:
        route = "full-jp"
        kana = _clean_kana_symbols(JP_INDEX[jp_key])
    elif en_key in EN_INDEX:
        route = "full-en"
        kana = _clean_kana_symbols(EN_INDEX[en_key])

    hits: Dict[str, Any] = {"full": None, "partial": []}
    if route is None and os.environ.get("COMPANY_PARTIAL_OVERRIDES", "0") not in ("", "0", "false", "False"):
        token_min = int(os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN", "2") or "2")
        allow_charwise = os.environ.get("PARTIAL_ACRONYM_CHARWISE", "0") not in ("", "0", "false", "False")
        acronym_max = int(os.environ.get("PARTIAL_ACRONYM_MAX_LEN", "3") or "3")

        view_en = _scan_view_en(stripped)
        view_jp = _scan_view_jp(stripped)
        en_keys = []
        jp_keys = []
        if EN_TOK:
            en_keys = [k for k in EN_TOK.keys() if len(k) >= token_min]
            en_keys.sort(key=lambda x: (-len(x), x))
        if JP_TOK:
            jp_keys = [k for k in JP_TOK.keys() if len(k) >= token_min]
            jp_keys.sort(key=lambda x: (-len(x), x))

        n = len(stripped)
        i = 0
        out_parts: List[str] = []
        gap_buf: List[str] = []

        def flush_gap():
            if gap_buf:
                seg = "".join(gap_buf)
                gap_buf.clear()
                if seg.strip():
                    out_parts.append(_clean_kana_symbols(_to_kata(seg)))

        def _is_ascii_alnum(ch: str) -> bool:
            return ("a" <= ch <= "z") or ("0" <= ch <= "9")

        while i < n:
            ch = stripped[i]
            if _is_sep(ch):
                flush_gap()
                i += 1
                continue

            matched = None
            if JP_TOK:
                for t in jp_keys:
                    tl = len(t)
                    if tl > 0 and i + tl <= n and view_jp[i:i+tl] == t:
                        matched = ("jp", t, tl, _clean_kana_symbols(JP_TOK[t]))
                        break
            if matched is None and EN_TOK:
                for t in en_keys:
                    tl = len(t)
                    if tl > 0 and i + tl <= n and view_en[i:i+tl] == t:
                        prev_ok = (i == 0) or not _is_ascii_alnum(view_en[i-1])
                        next_ok = (i + tl == n) or not _is_ascii_alnum(view_en[i+tl])
                        if prev_ok or next_ok:
                            matched = ("en", t, tl, _clean_kana_symbols(EN_TOK[t]))
                            break

            if matched is not None:
                flush_gap()
                tag, t, tl, kana_piece = matched
                out_parts.append(kana_piece)
                hits["partial"].append((tag, t))
                i += tl
                continue

            if allow_charwise and view_en[i].isalnum():
                j = i
                while j < n and view_en[j].isalnum():
                    j += 1
                run_len = j - i
                if 1 <= run_len <= acronym_max and EN_TOK:
                    flush_gap()
                    for k in range(i, j):
                        ch_en = view_en[k]
                        if ch_en in EN_TOK:
                            out_parts.append(_clean_kana_symbols(EN_TOK[ch_en]))
                            hits["partial"].append(("en-char", ch_en))
                        else:
                            gap_buf.append(stripped[k])
                    i = j
                    continue

            gap_buf.append(ch)
            i += 1

        flush_gap()
        if out_parts:
            route = "partial"
            kana = _clean_kana_symbols("".join(out_parts))

    if route is None:
        route = "guess"
        kana = _clean_kana_symbols(_to_kata(stripped))

    return {
        "input": name,
        "stripped": stripped,
        "jp_key": jp_key,
        "en_key": en_key,
        "route": route,
        "hits": hits,
        "kana": kana,
    }

# ---- 会社辞書ローダ（JP/EN） ----
def _load_company_overrides() -> tuple[
    Dict[str, str], Dict[str, str], Dict[str, Any], Dict[str, Any], Dict[str, str], Dict[str, str]
]:
    jp_obj = _load_json(_data_path("data", "company_kana_overrides_jp.json")) or {}
    en_obj = _load_json(_data_path("data", "company_kana_overrides_en.json")) or {}

    jp_norm = jp_obj.get("normalize") or {}
    en_norm = en_obj.get("normalize") or {}

    jp_ovr = jp_obj.get("overrides") or {}
    en_ovr = en_obj.get("overrides") or {}

    jp_tok = jp_obj.get("tokens") or {}
    en_tok = en_obj.get("tokens") or {}

    jp_index: Dict[str, str] = {_normalize_for_jp_cfg(k, jp_norm): v for k, v in jp_ovr.items()}
    en_index: Dict[str, str] = {_normalize_for_en_cfg(k, en_norm): v for k, v in en_ovr.items()}

    jp_tokens: Dict[str, str] = {_normalize_for_jp_cfg(k, jp_norm): v for k, v in jp_tok.items()}
    en_tokens: Dict[str, str] = {_normalize_for_en_cfg(k, en_norm): v for k, v in en_tok.items()}

    return jp_index, en_index, jp_norm, en_norm, jp_tokens, en_tokens
