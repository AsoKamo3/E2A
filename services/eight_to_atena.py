# services/eight_to_atena.py
# v2.31
# 目的：
#  - Eightエクスポート（CSV/TSV）テキストを受け取り、
#    「姓かな・名かな・姓名かな・会社名かな（いずれもカタカナ）」を付与して CSV で返す
#  - 会社名かなは company_kana_overrides.json を最優先
#  - 法人格は corp_terms.json を参照（壊れていればフェールセーフ）
#  - 文字種整形や住所関連はこのモジュールでは行わない（textnorm に委譲）
#
# app.py v1.18 が参照する公開API：
#  - __version__
#  - convert_eight_csv_text_to_atena_csv_text(text: str) -> str

from __future__ import annotations
import os
import io
import csv
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# textnorm の関数は将来拡張用に一部だけ利用（現状の変換では直接未使用でもAPI整合のため残置）
from utils.textnorm import (
    to_zenkaku,
    normalize_block_notation,
    normalize_postcode,
    normalize_phone,
    load_bldg_words,
    bldg_words_version,
)

__version__ = "v2.31"
KANA_PIPELINE_VERSION = "v1.0.0"

# ------------------------------------------------------------
# データパス
# ------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BASE_DIR / "data"

_COMPANY_OVERRIDES_PATH = _DATA_DIR / "company_kana_overrides.json"
_CORP_TERMS_PATH = _DATA_DIR / "corp_terms.json"

# ------------------------------------------------------------
# フェールセーフ（法人格）
# ------------------------------------------------------------
_FALLBACK_CORP_TERMS = [
    "株式会社", "合同会社", "有限会社", "合資会社", "合名会社", "相互会社",
    "ＮＰＯ法人", "独立行政法人", "特定非営利活動法人", "地方独立行政法人",
    "医療法人", "医療法人財団", "医療法人社団",
    "財団法人", "一般財団法人", "公益財団法人",
    "社団法人", "一般社団法人", "公益社団法人",
    "社会福祉法人", "学校法人", "公立大学法人", "国立大学法人",
    "宗教法人", "中間法人", "特殊法人", "特例民法法人",
    "特定目的会社", "特定目的信託",
    "有限責任事業組合", "有限責任中間法人",
]

def _load_json_safe(p: Path, default):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# ------------------------------------------------------------
# オーバーライド辞書 / 法人格辞書
# ------------------------------------------------------------
_COMPANY_OVERRIDE_MAP: Dict[str, str] = {}
_COMPANY_OVERRIDE_VERSION = "unknown"

def _load_company_overrides() -> None:
    global _COMPANY_OVERRIDE_MAP, _COMPANY_OVERRIDE_VERSION
    obj = _load_json_safe(_COMPANY_OVERRIDES_PATH, {})
    if isinstance(obj, dict) and obj:
        _COMPANY_OVERRIDE_VERSION = obj.get("version", "unknown")
        mapping = obj.get("overrides")
        # { "overrides": { "会社名": "カナ", ... } } を推奨
        if isinstance(mapping, dict):
            _COMPANY_OVERRIDE_MAP = {str(k): str(v) for k, v in mapping.items()}
        else:
            # 旧形式 { "会社名": "カナ", "version": "..."} も許容
            _COMPANY_OVERRIDE_MAP = {
                str(k): str(v) for k, v in obj.items() if k not in ("version",)
            }
    else:
        _COMPANY_OVERRIDE_MAP = {}
        _COMPANY_OVERRIDE_VERSION = "unknown"

_load_company_overrides()

_CORP_TERMS_OBJ = _load_json_safe(_CORP_TERMS_PATH, {})
_CORP_TERMS_VERSION = _CORP_TERMS_OBJ.get("version", "unknown") if isinstance(_CORP_TERMS_OBJ, dict) else "unknown"
if isinstance(_CORP_TERMS_OBJ, dict) and isinstance(_CORP_TERMS_OBJ.get("terms"), list):
    _CORP_TERMS: List[str] = [str(t) for t in _CORP_TERMS_OBJ["terms"]]
else:
    _CORP_TERMS = _FALLBACK_CORP_TERMS
    _CORP_TERMS_VERSION = "fallback"

_CORP_TERMS_SORTED = sorted(_CORP_TERMS, key=len, reverse=True)

# ------------------------------------------------------------
# かな変換（pykakasi 使用。なければフォールバック）
# ------------------------------------------------------------
try:
    from pykakasi import kakasi  # type: ignore
    _KAKASI_OK = True
except Exception as e:
    kakasi = None  # type: ignore
    _KAKASI_OK = False
    _KAKASI_ERR = f"pykakasi import error: {e}"
else:
    _KAKASI_ERR = "pykakasi ok"

def _hiragana_to_katakana(s: str) -> str:
    out = []
    for ch in s or "":
        code = ord(ch)
        if 0x3041 <= code <= 0x3096:  # ひらがな -> カタカナ
            out.append(chr(code + 0x60))
        else:
            out.append(ch)
    return "".join(out)

def _force_katakana(s: str) -> str:
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKC", s)
    return _hiragana_to_katakana(s)

def _pykakasi_to_hira(s: str) -> str:
    if not _KAKASI_OK or kakasi is None:
        return unicodedata.normalize("NFKC", s or "")
    kks = kakasi()
    kks.setMode("J", "H")  # 漢字→ひらがな
    kks.setMode("K", "H")  # カタカナ→ひらがな
    kks.setMode("H", "H")  # ひらがな維持
    conv = kks.getConverter()
    return conv.do(s or "")

def _name_to_katakana(s: str) -> str:
    return _force_katakana(_pykakasi_to_hira(s or ""))

def _strip_corp_term_prefix(company: str) -> Tuple[str, str]:
    if not company:
        return "", ""
    s = unicodedata.normalize("NFKC", company)
    for term in _CORP_TERMS_SORTED:
        if s.startswith(term):
            return term, s[len(term):].lstrip()
    # スペースの揺れにも最低限対応
    s_no_space = s.replace(" ", "")
    for term in _CORP_TERMS_SORTED:
        if s_no_space.startswith(term):
            return term, s_no_space[len(term):].lstrip()
    return "", s

def _company_to_katakana(company: str) -> str:
    if not company:
        return ""
    key = unicodedata.normalize("NFKC", company)
    # オーバーライド最優先
    if key in _COMPANY_OVERRIDE_MAP:
        return _force_katakana(_COMPANY_OVERRIDE_MAP[key])

    # 法人格を外して本体のみ読む
    _, body = _strip_corp_term_prefix(key)
    kana_body = _force_katakana(_pykakasi_to_hira(body or key))
    return kana_body

# ------------------------------------------------------------
# 行変換（かな付与）
# ------------------------------------------------------------
COL_LAST = "姓"
COL_FIRST = "名"
COL_LAST_KANA = "姓かな"
COL_FIRST_KANA = "名かな"
COL_FULL = "姓名"
COL_FULL_KANA = "姓名かな"
COL_COMPANY = "会社名"
COL_COMPANY_KANA = "会社名かな"

def enrich_row_with_kana(row: Dict[str, str], *, enable_furigana: bool = True) -> Dict[str, str]:
    if not isinstance(row, dict):
        return row

    def _need(v): return (v is None) or (str(v).strip() == "")

    last = str(row.get(COL_LAST) or "")
    first = str(row.get(COL_FIRST) or "")
    full = str(row.get(COL_FULL) or (last + first))
    company = str(row.get(COL_COMPANY) or "")

    if enable_furigana:
        if _need(row.get(COL_LAST_KANA)):
            row[COL_LAST_KANA] = _name_to_katakana(last) if last else ""
        if _need(row.get(COL_FIRST_KANA)):
            row[COL_FIRST_KANA] = _name_to_katakana(first) if first else ""
        if _need(row.get(COL_FULL_KANA)):
            if full:
                row[COL_FULL_KANA] = _name_to_katakana(full)
            elif last or first:
                row[COL_FULL_KANA] = (row.get(COL_LAST_KANA) or "") + (row.get(COL_FIRST_KANA) or "")
            else:
                row[COL_FULL_KANA] = ""
        if _need(row.get(COL_COMPANY_KANA)):
            row[COL_COMPANY_KANA] = _company_to_katakana(company) if company else ""
    else:
        # フリガナ無効時は既存値を壊さず埋めない
        row.setdefault(COL_LAST_KANA, row.get(COL_LAST_KANA) or "")
        row.setdefault(COL_FIRST_KANA, row.get(COL_FIRST_KANA) or "")
        row.setdefault(COL_FULL_KANA, row.get(COL_FULL_KANA) or "")
        row.setdefault(COL_COMPANY_KANA, row.get(COL_COMPANY_KANA) or "")

    return row

def enrich_rows(rows: List[Dict[str, str]], *, enable_furigana: Optional[bool] = None) -> List[Dict[str, str]]:
    if enable_furigana is None:
        enable_furigana = (os.environ.get("FURIGANA_ENABLED") == "1")
    return [enrich_row_with_kana(dict(r), enable_furigana=enable_furigana) for r in rows]

# ------------------------------------------------------------
# CSV/TSV → CSV 変換の外部公開関数（app.py が呼び出す）
# ------------------------------------------------------------
_KANA_COLS = [COL_LAST_KANA, COL_FIRST_KANA, COL_FULL_KANA, COL_COMPANY_KANA]

def _detect_delimiter(head_line: str) -> str:
    tabs = head_line.count("\t")
    commas = head_line.count(",")
    return "\t" if tabs > commas else ","

def convert_eight_csv_text_to_atena_csv_text(text: str) -> str:
    """
    入力：Eightエクスポート（CSV/TSVテキスト）
    出力：CSVテキスト（カンマ区切り固定）
    """
    if not isinstance(text, str):
        raise TypeError("text must be str")

    # 区切り自動判定
    first_line = text.splitlines()[0] if text else ""
    src_delim = _detect_delimiter(first_line)

    # 読み込み
    src = io.StringIO(text)
    reader = csv.DictReader(src, delimiter=src_delim)
    rows = [dict(r) for r in reader]
    headers: List[str] = list(reader.fieldnames or [])

    # かな列が無ければ追加（末尾）
    for kcol in _KANA_COLS:
        if kcol not in headers:
            headers.append(kcol)

    # かな付与
    enriched = enrich_rows(rows)

    # 書き出し（CSV固定）
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for r in enriched:
        # 欠落キーは空文字で埋める
        for h in headers:
            if h not in r:
                r[h] = ""
        writer.writerow(r)

    return out.getvalue()

# ------------------------------------------------------------
# healthz などから参照される補助（必要なら app.py で利用可）
# ------------------------------------------------------------
def furigana_engine_name() -> str:
    return "pykakasi" if _KAKASI_OK else "fallback"

def furigana_engine_detail() -> str:
    return _KAKASI_ERR

def company_overrides_version() -> str:
    return _COMPANY_OVERRIDE_VERSION

def corp_terms_version() -> str:
    return _CORP_TERMS_VERSION

def kana_pipeline_version() -> str:
    return KANA_PIPELINE_VERSION
