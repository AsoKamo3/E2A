# utils/textnorm.py
# v1.14
# 最小限・安定版：既存呼び出し点で使われる関数のみを提供
from __future__ import annotations
import re
import json
import unicodedata
from pathlib import Path

try:
    import jaconv  # 半全角変換
except Exception:
    jaconv = None  # フェールセーフ

__all__ = [
    "to_zenkaku",
    "normalize_block_notation",
    "normalize_postcode",
    "normalize_phone",
    "load_bldg_words",
    "bldg_words_version",
    "BZ_WORDS",
    "__version__",
]

__version__ = "v1.14"

# ---- 建物語彙のロード -----------------------------------------------------

_BLDG_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "bldg_words.json"
BZ_WORDS = set()
_BLDG_VERSION = "unknown"

def load_bldg_words() -> set[str]:
    """data/bldg_words.json を読み込み、語彙セットを返す。"""
    global BZ_WORDS, _BLDG_VERSION
    if BZ_WORDS:
        return BZ_WORDS
    try:
        with _BLDG_JSON_PATH.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        words = obj.get("words") or obj.get("list") or []
        _BLDG_VERSION = obj.get("version", "unknown")
        BZ_WORDS = set(map(str, words))
    except Exception:
        BZ_WORDS = set()
        _BLDG_VERSION = "unknown"
    return BZ_WORDS

def bldg_words_version() -> str:
    """bldg_words.json のバージョン文字列を返す。"""
    # 事前に load していなくても返せるように軽く読む
    global _BLDG_VERSION
    if _BLDG_VERSION != "unknown":
        return _BLDG_VERSION
    try:
        with _BLDG_JSON_PATH.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        _BLDG_VERSION = obj.get("version", "unknown")
    except Exception:
        _BLDG_VERSION = "unknown"
    return _BLDG_VERSION

# ---- 文字種・記号ノーマライズ --------------------------------------------

_HYPHENS = [
    "-", "‐", "-", "‒", "–", "—", "―", "ー", "ｰ", "－",
]

def _unify_hyphen(s: str, to="-" ) -> str:
    for h in _HYPHENS:
        s = s.replace(h, to)
    return s

def to_zenkaku(s: str) -> str:
    """
    可能なら jaconv でASCII/数字/かなを全角へ。無ければNFKCのみ。
    """
    s = "" if s is None else str(s)
    if jaconv:
        return jaconv.h2z(s, ascii=True, digit=True, kana=True)
    # フォールバック：NFKCで正規化し、ハイフン類を全角に寄せない（最小）
    return unicodedata.normalize("NFKC", s)

def normalize_block_notation(s: str) -> str:
    """
    住居表示の「番地・号」周りの表記ゆれを緩く整形。
    - ハイフン類を半角ハイフンに統一
    - 全角/半角の数字は一旦NFKCに寄せる
    例: "１－８－１" → "1-8-1"
    """
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKC", s)
    s = _unify_hyphen(s, "-")
    # 連続ハイフンは1個へ
    s = re.sub(r"-{2,}", "-", s)
    return s

# ---- 郵便番号ノーマライズ -------------------------------------------------

_POST_RE = r
