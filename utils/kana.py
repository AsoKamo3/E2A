# utils/kana.py
# ふりがな自動付与（推測）モジュール v0.8
# - FURIGANA_ENABLED="1" で有効（デフォルト: 有効）
# - pykakasi が使えればそれを利用。失敗時は簡易（ひら→カタカナ）にフォールバック
# - engine_name()/engine_detail() で現在エンジン状態を返す

from __future__ import annotations
import os
import re
import importlib.util
from typing import Literal, Tuple

__version__ = "v0.8"

_HIRA2KATA_TABLE = {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}  # ぁ-ゖ

_RE_HAS_JA = re.compile(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]")
_RE_HAS_HIRA = re.compile(r"[ぁ-ん]")
_RE_ASCII_ONLY = re.compile(r"^[\x00-\x7F]+$")

def _hira_to_kata(s: str) -> str:
    if not s:
        return ""
    return s.translate(_HIRA2KATA_TABLE)

def _guess_simple(s: str) -> str:
    """ひらがなが含まれていれば ひら→カタカナ。含まれなければ空（誤推測しない）。"""
    if not s:
        return ""
    if _RE_HAS_HIRA.search(s):
        return _hira_to_kata(s)
    return ""

def _pykakasi_to_kata(s: str) -> str:
    try:
        import pykakasi  # type: ignore
        kks = pykakasi.kakasi()
        parts = kks.convert(s)
        hira = "".join(p.get("hira", "") or p.get("kana", "") for p in parts)
        return _hira_to_kata(hira)
    except Exception:
        return _guess_simple(s)

def to_katakana_guess(s: str) -> str:
    """
    カタカナの読みを推測して返す。
    - FURIGANA_ENABLED != "1" → ""（無効）
    - ASCII のみ / 日本語文字が無い → ""（誤推測しない）
    - pykakasi があれば使用、無ければ簡易
    """
    if not s:
        return ""
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return ""
    if _RE_ASCII_ONLY.fullmatch(s or ""):
        return ""
    if not _RE_HAS_JA.search(s):
        return ""
    return _pykakasi_to_kata(s)

def engine_name() -> Literal["pykakasi", "fallback", "disabled"]:
    """現在のふりがなエンジンの状態を返す。"""
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return "disabled"
    spec = importlib.util.find_spec("pykakasi")
    if not spec:
        return "fallback"
    try:
        import pykakasi  # type: ignore
        _ = pykakasi.kakasi()
        return "pykakasi"
    except Exception:
        return "fallback"

def engine_detail() -> Tuple[str, str]:
    """
    (engine, detail) を返す。
    detail 例:
      ("pykakasi","pykakasi ok")
      ("fallback","pykakasi spec: None") / ("fallback","pykakasi error: ModuleNotFoundError")
      ("disabled","env FURIGANA_ENABLED!=1")
    """
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return ("disabled", "env FURIGANA_ENABLED!=1")
    spec = importlib.util.find_spec("pykakasi")
    if not spec:
        return ("fallback", "pykakasi spec: None")
    try:
        import pykakasi  # type: ignore
        _ = pykakasi.kakasi()
        return ("pykakasi", "pykakasi ok")
    except Exception as e:
        return ("fallback", f"pykakasi error: {e.__class__.__name__}")
