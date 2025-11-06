# utils/textnorm.py
# v1.13: restore __version__; keep the minimal, stable APIs from v1.12
# Exposes:
#   - to_zenkaku
#   - normalize_postcode
#   - normalize_block_notation
#   - load_bldg_words
#   - bldg_words_version

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Tuple

__version__ = "v1.13"

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_BLDG_JSON = _DATA_DIR / "bldg_words.json"

__all__ = [
    "__version__",
    "to_zenkaku",
    "normalize_postcode",
    "normalize_block_notation",
    "load_bldg_words",
    "bldg_words_version",
]

# -----------------------------
# Basic normalization utilities
# -----------------------------

def to_zenkaku(text: str) -> str:
    """
    NFKC 正規化（半角→全角・互換文字の正規化）。
    住所・会社名・人名など広範に使うため、副作用の強い置換は行わない。
    """
    if text is None:
        return ""
    return unicodedata.normalize("NFKC", str(text))


# -----------------------------
# Postcode normalization
# -----------------------------

# ハイフン類を ASCII ハイフンへ寄せるための正規表現
_POSTCODE_RE = re.compile(r"(\d)[\-\u2212\u2010-\u2015\u30fc\uFF0D\u2013\u2014](\d)")
_ONLY_DIGITS_RE = re.compile(r"\D+")

def normalize_postcode(text: str) -> str:
    """
    郵便番号を「123-4567」形式に整える（数字が7桁あれば整形）。
    7桁未満/超のときは、NFKC正規化＋ハイフン統一のみ行う。
    例:
      "１００  -  ８４３９" -> "100-8439"
      "1008439"           -> "100-8439"
    """
    if not text:
        return ""
    s = to_zenkaku(text).strip()
    digits = _ONLY_DIGITS_RE.sub("", s)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    # ハイフン類を ASCII ハイフンに統一
    s = _POSTCODE_RE.sub(r"\1-\2", s)
    return s


# -----------------------------
# Block notation normalization
# -----------------------------

_HYPHENS = r"[\-\u2212\u2010-\u2015\u30fc\uFF0D\u2013\u2014]"
_BLOCK_RE = re.compile(rf"\s*({_HYPHENS})\s*")

def normalize_block_notation(text: str) -> str:
    """
    番地/号などの「1-2-3」表記をゆるく正規化。
      - 多様なハイフンを ASCII '-' に統一
      - ハイフン前後の余分な空白を除去
      - 連続ハイフンは 1 本化
    それ以外は壊さない（全角数字・漢数字・ビル名等は触らない）
    """
    if not text:
        return ""
    s = to_zenkaku(text)
    s = _BLOCK_RE.sub("-", s)      # ハイフン周りの空白も同時に整理
    s = re.sub(r"-{2,}", "-", s)   # 連続ハイフンの1本化
    return s.strip()


# -----------------------------
# Building words dictionary
# -----------------------------

@lru_cache(maxsize=1)
def load_bldg_words() -> Tuple[Dict[str, Any], str]:
    """
    data/bldg_words.json を読み込む。
    返り値: (payload, version)
      - payload: JSON本体（辞書）
      - version: JSON内の "version" があればそれ、無ければ "unknown"
    """
    payload: Dict[str, Any] = {}
    version = "unknown"
    if _BLDG_JSON.exists():
        try:
            payload = json.loads(_BLDG_JSON.read_text(encoding="utf-8"))
            version = str(payload.get("version", "unknown"))
        except Exception:
            payload = {}
            version = "unknown"
    return payload, version


def bldg_words_version() -> str:
    """bldg_words.json のバージョン文字列を返す（無ければ "unknown"）。"""
    _, ver = load_bldg_words()
    return ver
