# utils/textnorm.py
# v1.15
# - BUGFIX: stray 'r' による NameError を修正
# - app.py/eight_to_atena.py が参照する関数だけを厳選し提供
# - 各辞書のバージョン問い合わせは存在しない/壊れている場合でもフェールセーフ

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__version__ = "v1.15"

# ---------------------------------------------------------------------
# 内部: パスと安全ロード
# ---------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BASE_DIR / "data"

_BLDG_WORDS_PATH = _DATA_DIR / "bldg_words.json"            # {"version":"v1.0.0", "words":[...]}
_CORP_TERMS_PATH = _DATA_DIR / "corp_terms.json"            # {"version":"v1.0.1", "terms":[...]}
_COMPANY_OVR_PATH = _DATA_DIR / "company_kana_overrides.json"  # {"version":"v1.x", "overrides":{...}}

def _load_json_safe(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# ---------------------------------------------------------------------
# 文字種・全角化
# ---------------------------------------------------------------------
def to_zenkaku(s: Optional[str]) -> str:
    """半角→全角（記号やラテン文字・数字もふくめ NFKC 正規化）"""
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s))

# ---------------------------------------------------------------------
# 郵便番号
# ---------------------------------------------------------------------
# ★ ここが v1.13 で壊れていた箇所（stray 'r'）→ 正しい正規表現に修正
_POST_RE = re.compile(r"(\d{3})[-\u2212\u30FC\u2010-\u2015\uFE63\uFF0D]?(\d{4})")

def normalize_postcode(s: Optional[str]) -> str:
    """郵便番号を NNN-NNNN に整える。見つからない場合は空文字。"""
    if not s:
        return ""
    txt = unicodedata.normalize("NFKC", str(s))
    m = _POST_RE.search(txt)
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}"

# ---------------------------------------------------------------------
# ブロック/番地表記のハイフン正規化（軽量）
# ---------------------------------------------------------------------
# 半角・全角・ダッシュ系のゆらぎを半角ハイフンに寄せる
_DASH_CHARS = "-\u2212\u30FC\u2010\u2011\u2012\u2013\u2014\u2015\uFE63\uFF0D"
_DASH_CLASS = f"[{_DASH_CHARS}]"

def normalize_block_notation(s: Optional[str]) -> str:
    """
    番地・号などのダッシュを半角に統一。住所全体を壊さない軽量処理。
    例: '1－2–3' → '1-2-3'
    """
    if not s:
        return ""
    txt = unicodedata.normalize("NFKC", str(s))
    return re.sub(_DASH_CLASS, "-", txt)

# ---------------------------------------------------------------------
# 電話番号（軽量）
# ---------------------------------------------------------------------
# +81, 0X, 内線の簡易吸収。厳格な地域判定は行わず、一般的な 10/11 桁に整形。
_DIGITS_RE = re.compile(r"\d+")
_PLUS81_RE = re.compile(r"^\+?81")

def _only_digits(s: str) -> str:
    return "".join(_DIGITS_RE.findall(s))

def normalize_phone(s: Optional[str]) -> str:
    """
    電話番号を軽量正規化。
    - 全角→半角/NFKC
    - 国番号 +81 → 先頭 0 に寄せる
    - 10桁 → 0AA-BBBB-CCCC / 11桁 → 0AAA-BBBB-CCCC（目安）
    - それ以外は数字のみ返す（桁不定形はハイフン付与しない）
    """
    if not s:
        return ""
    txt = unicodedata.normalize("NFKC", str(s)).strip()

    # 国番号形式を 0 始まりに寄せる
    if _PLUS81_RE.match(txt):
        # +81-3-... / +81(0)90-... などを 0 始まりへ
        txt = _PLUS81_RE.sub("0", txt)
        txt = txt.replace("(0)", "0")

    digits = _only_digits(txt)

    # 代表ケース 10/11 桁
    if len(digits) == 10:
        return f"{digits[0:2]}-{digits[2:6]}-{digits[6:10]}" if digits.startswith("0") else f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    if len(digits) == 11:
        return f"{digits[0:3]}-{digits[3:7]}-{digits[7:11]}"

    # 桁不一致は数字のみ（過剰な誤判定を避ける）
    return digits

# ---------------------------------------------------------------------
# 建物語彙（軽量ローダ）
# ---------------------------------------------------------------------
# 期待形式: {"version":"v1.0.0","words":["ビル","マンション",...]}
_BLDG_WORDS: List[str] = []
_BLDG_WORDS_VERSION: str = "unknown"

def load_bldg_words() -> List[str]:
    """建物語彙の配列（存在しなければ空配列）。"""
    global _BLDG_WORDS, _BLDG_WORDS_VERSION
    if _BLDG_WORDS:
        return _BLDG_WORDS
    obj = _load_json_safe(_BLDG_WORDS_PATH, {})
    if isinstance(obj, dict):
        _BLDG_WORDS_VERSION = str(obj.get("version", "unknown"))
        words = obj.get("words") or obj.get("list") or []
        if isinstance(words, list):
            _BLDG_WORDS = [str(w) for w in words]
        else:
            _BLDG_WORDS = []
    else:
        _BLDG_WORDS = []
        _BLDG_WORDS_VERSION = "unknown"
    return _BLDG_WORDS

def bldg_words_version() -> str:
    """建物語彙の辞書版を返す（存在しなければ 'unknown'）。"""
    global _BLDG_WORDS_VERSION
    if not _BLDG_WORDS:
        load_bldg_words()
    return _BLDG_WORDS_VERSION

# ---------------------------------------------------------------------
# corp_terms / company_overrides のバージョン照会（app の表示用）
# ---------------------------------------------------------------------
def corp_terms_version() -> str:
    obj = _load_json_safe(_CORP_TERMS_PATH, {})
    if isinstance(obj, dict) and "version" in obj:
        return str(obj.get("version"))
    return "unknown"

def company_overrides_version() -> str:
    obj = _load_json_safe(_COMPANY_OVR_PATH, {})
    if isinstance(obj, dict):
        if "version" in obj:
            return str(obj.get("version"))
        # 旧形式 { "会社名": "カナ", "version": "..."} に配慮
        v = obj.get("version")
        return str(v) if v is not None else "unknown"
    return "unknown"

# ---------------------------------------------------------------------
# エクスポート
# ---------------------------------------------------------------------
__all__ = [
    "__version__",
    # text
    "to_zenkaku",
    "normalize_block_notation",
    "normalize_postcode",
    "normalize_phone",
    # dicts
    "load_bldg_words",
    "bldg_words_version",
    "corp_terms_version",
    "company_overrides_version",
]
