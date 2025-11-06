# services/eight_to_atena.py
# v2.30
# 目的：
#  - 連絡先行の辞書に「姓かな・名かな・姓名かな・会社名かな（すべてカタカナ）」を付与
#  - 会社名かなは company_kana_overrides.json を最優先、なければ簡易変換
#  - 法人格は corp_terms.json を参照（見つからなければ内蔵リストでフェールセーフ）
#  - 文字種整形や郵便・電話整形は utils.textnorm に委譲（関数名を変更しない）
#
# 依存（提供済み）:
#  - utils.textnorm: to_zenkaku, normalize_block_notation, normalize_postcode,
#                    normalize_phone, load_bldg_words, bldg_words_version
#  - data/company_kana_overrides.json
#  - data/corp_terms.json
#
# app.py からは本モジュールのバージョンと関数群が呼ばれます。

from __future__ import annotations
import os
import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from utils.textnorm import (
    to_zenkaku,
    normalize_block_notation,
    normalize_postcode,
    normalize_phone,
    load_bldg_words,
    bldg_words_version,
)

# ---------------------------------------------------------------------
# メタ情報
# ---------------------------------------------------------------------

__version__ = "v2.30"            # このモジュール（変換器）のバージョン
KANA_PIPELINE_VERSION = "v1.0.0"  # かな付与処理のバージョン（healthz 表示用の識別）

# ---------------------------------------------------------------------
# 外部辞書のロード（オーバーライド／法人格）
# ---------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parent.parent  # プロジェクトルート（src直下想定）
_DATA_DIR = _BASE_DIR / "data"

_COMPANY_OVERRIDES_PATH = _DATA_DIR / "company_kana_overrides.json"
_CORP_TERMS_PATH = _DATA_DIR / "corp_terms.json"

# フェールセーフ用の最小法人格（JSONが壊れていても最低限動作）
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

# 会社名→カナ読み のオーバーライド辞書
_COMPANY_OVERRIDE_MAP: Dict[str, str] = {}
_COMPANY_OVERRIDE_VERSION = "unknown"

def _load_company_overrides() -> None:
    global _COMPANY_OVERRIDE_MAP, _COMPANY_OVERRIDE_VERSION
    obj = _load_json_safe(_COMPANY_OVERRIDES_PATH, {})
    if isinstance(obj, dict) and obj:
        _COMPANY_OVERRIDE_VERSION = obj.get("version", "unknown")
        mapping = obj.get("overrides")
        # 旧形式 { "会社名": "カナ" } でも許容
        if isinstance(mapping, dict):
            _COMPANY_OVERRIDE_MAP = {str(k): str(v) for k, v in mapping.items()}
        else:
            # 旧互換（ルート直下が map の場合）
            _COMPANY_OVERRIDE_MAP = {
                str(k): str(v) for k, v in obj.items() if k not in ("version",)
            }
    else:
        _COMPANY_OVERRIDE_MAP = {}
        _COMPANY_OVERRIDE_VERSION = "unknown"

_load_company_overrides()

# 法人格のリスト（JSON優先）
_CORP_TERMS_OBJ = _load_json_safe(_CORP_TERMS_PATH, {})
_CORP_TERMS_VERSION = _CORP_TERMS_OBJ.get("version", "unknown") if isinstance(_CORP_TERMS_OBJ, dict) else "unknown"
_CORP_TERMS: List[str] = []
if isinstance(_CORP_TERMS_OBJ, dict) and isinstance(_CORP_TERMS_OBJ.get("terms"), list):
    _CORP_TERMS = [str(t) for t in _CORP_TERMS_OBJ["terms"]]
else:
    _CORP_TERMS = _FALLBACK_CORP_TERMS
    _CORP_TERMS_VERSION = "fallback"

# 長い語を優先してマッチさせる（先頭一致用）
_CORP_TERMS_SORTED = sorted(_CORP_TERMS, key=len, reverse=True)

# ---------------------------------------------------------------------
# かな変換（人名・会社名）
#  - ひらがなに落ちた場合も最終的にはカタカナに強制
#  - pykakasi が無ければ簡易フォールバック
# ---------------------------------------------------------------------

try:
    from pykakasi import kakasi  # type: ignore
    _KAKASI_OK = True
except Exception as e:
    kakasi = None  # type: ignore
    _KAKASI_OK = False
    _KAKASI_ERR = str(e)
else:
    _KAKASI_ERR = "pykakasi ok"

def _hiragana_to_katakana(s: str) -> str:
    # かな領域の単純オフセットで変換（jaconv不在でも動く）
    out_chars = []
    for ch in s:
        code = ord(ch)
        # ひらがな範囲
        if 0x3041 <= code <= 0x3096:
            out_chars.append(chr(code + 0x60))
        else:
            out_chars.append(ch)
    return "".join(out_chars)

def _force_katakana(s: str) -> str:
    s = "" if s is None else str(s)
    # NFKC で合成文字を正規化
    s = unicodedata.normalize("NFKC", s)
    # ひらがなをカタカナへ
    return _hiragana_to_katakana(s)

def _pykakasi_to_hira(s: str) -> str:
    if not _KAKASI_OK or kakasi is None:
        # フォールバック：記号除去とNFKC程度。非日本語は読みにできないので入力を返す。
        return unicodedata.normalize("NFKC", s or "")
    kks = kakasi()
    kks.setMode("J", "H")  # 漢字→ひらがな
    kks.setMode("K", "H")  # カタカナ→ひらがな
    kks.setMode("H", "H")  # ひらがな維持
    conv = kks.getConverter()
    return conv.do(s or "")

def _name_to_katakana(s: str) -> str:
    """人名用：漢字かな交じり→カタカナ"""
    hira = _pykakasi_to_hira(s)
    return _force_katakana(hira)

def _strip_corp_term_prefix(company: str) -> Tuple[str, str]:
    """
    会社名先頭の法人格を取り出す。
    戻り値: (法人格, 本体名)  ※法人格が無ければ ("", 入力名)
    """
    if not company:
        return "", ""
    s = unicodedata.normalize("NFKC", company)
    for term in _CORP_TERMS_SORTED:
        if s.startswith(term):
            return term, s[len(term):].lstrip()
    # 「株式会社　〇〇」「株式会社〇〇」の半全角スペースばらつきにも一応対応
    for term in _CORP_TERMS_SORTED:
        if s.replace(" ", "").startswith(term):
            no_space = s.replace(" ", "")
            return term, no_space[len(term):].lstrip()
    return "", s

def _company_to_katakana(company: str) -> str:
    """
    会社名かな（カタカナ）を返す。
    1) 完全一致でオーバーライドにあればそれを返す
    2) 無ければ、法人格を除いた本体名を pykakasi でひらがな化→カタカナ化
       - ラテン文字・記号は読みにできないため、そのまま残ることがある
       - こうしたケースはオーバーライドでの上書きを想定
    """
    if not company:
        return ""
    company_n = unicodedata.normalize("NFKC", company)
    # まずはオーバーライド
    if company_n in _COMPANY_OVERRIDE_MAP:
        return _force_katakana(_COMPANY_OVERRIDE_MAP[company_n])

    # 法人格を外して本体を読む
    corp, body = _strip_corp_term_prefix(company_n)
    if body:
        kana_body = _force_katakana(_pykakasi_to_hira(body))
    else:
        kana_body = _force_katakana(_pykakasi_to_hira(company_n))

    # 読みの前に法人格カナを付すかは要件次第だが、
    # 既存の出力例は「本体だけのカナ」が多いため、ここでは本体のみを返す。
    return kana_body

# ---------------------------------------------------------------------
# 行変換（E→Atena）
# ---------------------------------------------------------------------

# 入出力で使う主な列名（存在しない場合は安全に無視）
COL_LAST = "姓"
COL_FIRST = "名"
COL_LAST_KANA = "姓かな"
COL_FIRST_KANA = "名かな"
COL_FULL = "姓名"
COL_FULL_KANA = "姓名かな"
COL_COMPANY = "会社名"
COL_COMPANY_KANA = "会社名かな"

def enrich_row_with_kana(row: Dict[str, str], *, enable_furigana: bool = True) -> Dict[str, str]:
    """
    1行（辞書）に かな列を付与。既に値がある場合は壊さない（空欄のみ埋める）。
    - 姓かな/名かな/姓名かな/会社名かな をカタカナで出力
    """
    if not isinstance(row, dict):
        return row

    # すでに値があれば保持（空欄扱い基準：None/""）
    def _need(v): return v is None or str(v).strip() == ""

    last = str(row.get(COL_LAST) or "")
    first = str(row.get(COL_FIRST) or "")
    full = str(row.get(COL_FULL) or (last + first))
    company = str(row.get(COL_COMPANY) or "")

    # 人名かな
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
    else:
        # フリガナ無効時は空欄のまま（壊さない）
        row.setdefault(COL_LAST_KANA, row.get(COL_LAST_KANA) or "")
        row.setdefault(COL_FIRST_KANA, row.get(COL_FIRST_KANA) or "")
        row.setdefault(COL_FULL_KANA, row.get(COL_FULL_KANA) or "")

    # 会社名かな
    if enable_furigana:
        if _need(row.get(COL_COMPANY_KANA)):
            row[COL_COMPANY_KANA] = _company_to_katakana(company) if company else ""
    else:
        row.setdefault(COL_COMPANY_KANA, row.get(COL_COMPANY_KANA) or "")

    return row

def enrich_rows(rows: List[Dict[str, str]], *, enable_furigana: Optional[bool] = None) -> List[Dict[str, str]]:
    """
    複数行をかな付与。環境変数 FURIGANA_ENABLED が "1" なら有効。
    """
    if enable_furigana is None:
        enable_furigana = (os.environ.get("FURIGANA_ENABLED") == "1")
    out = []
    for r in rows:
        out.append(enrich_row_with_kana(dict(r), enable_furigana=enable_furigana))
    return out

# ---------------------------------------------------------------------
# healthz 用の補助（app.py から表示用に参照されることを想定）
# ---------------------------------------------------------------------

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

# ---------------------------------------------------------------------
# ここでは住所分解や電話・郵便の整形は行わない（textnorm に委譲）。
# 本モジュールは「かな付与と、その周辺（会社名オーバーライド/法人格処理）」に専念。
# ---------------------------------------------------------------------
