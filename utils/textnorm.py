# utils/textnorm.py
# 文字種正規化・番地表記正規化・建物語辞書ロード
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import List, Any

__version__ = "v1.10"
__meta__ = {
    "features": [
        "to_zenkaku (NFKC)",
        "to_zenkaku_wide (ASCII→全角：数字/英字/記号/スペース)",
        "normalize_block_notation",
        "normalize_postcode (###-####・不正は空)",
        "load_bldg_words (array or {version,words})",
        "bldg_words_version()",
    ],
}

_BLDG_VERSION: str | None = None

def to_zenkaku(s: str) -> str:
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", s)

def to_zenkaku_wide(s: str) -> str:
    if not s:
        return ""
    out = []
    for ch in s:
        oc = ord(ch)
        if ch == " ":
            out.append("\u3000")
        elif 0x21 <= oc <= 0x7E:
            out.append(chr(oc + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)

def normalize_postcode(s: str) -> str:
    """
    郵便番号を ###-#### で返す（7桁以外は空）。
    入力は NFKC 後に数字のみ抽出。
    """
    if not s:
        return ""
    x = to_zenkaku(s)
    digits = "".join(ch for ch in x if ch.isdigit())
    if len(digits) != 7:
        return ""
    return digits[:3] + "-" + digits[3:]

_DEF_REPLACERS = [
    (r"\s+", ""),
    (r"丁目", "-"),
    (r"番地", "-"),
    (r"番", "-"),
    (r"号", "-"),
    (r"の", "-"),
    (r"－", "-"),
    (r"[‐‒–—―ｰ−]", "-"),
    (r"-{2,}", "-"),
    (r"(^-|-$)", ""),
]

def normalize_block_notation(s: str) -> str:
    if not s:
        return ""
    x = to_zenkaku(s)
    for pat, rep in _DEF_REPLACERS:
        x = re.sub(pat, rep, x)
    return x

def _candidate_paths(path: str | None) -> list[str]:
    c: list[str] = []
    if path:
        c.append(path)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    c.append(os.path.join(root, "data", "bldg_words.json"))
    c.append(os.path.join(here, "bldg_words.json"))
    return c

def _dedup_nonempty(items: list[Any]) -> list[str]:
    seen = set()
    out: list[str] = []
    for w in items:
        s = str(w).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out

def load_bldg_words(path: str | None = None) -> List[str]:
    global _BLDG_VERSION
    _BLDG_VERSION = None
    for p in _candidate_paths(path):
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    ver = str(data.get("version") or "").strip() or None
                    words = data.get("words")
                    if isinstance(words, list):
                        _BLDG_VERSION = ver
                        return _dedup_nonempty(words)
                if isinstance(data, list):
                    return _dedup_nonempty(data)
        except Exception:
            continue
    return []

def bldg_words_version() -> str | None:
    return _BLDG_VERSION
