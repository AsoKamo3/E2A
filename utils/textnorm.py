# utils/textnorm.py
# 文字種正規化・番地表記正規化・建物語辞書ロード
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import List, Any

__version__ = "v1.8"
__meta__ = {
    "features": [
        "to_zenkaku (NFKC)",
        "to_zenkaku_wide (ASCII→全角：数字/英字/記号/スペース)",
        "normalize_block_notation",
        "load_bldg_words (array or {version,words})",
        "bldg_words_version()",
    ],
}

# 内部にロードした辞書版を保持（配列JSONの場合は None）
_BLDG_VERSION: str | None = None

# --- NFKC 全角化（互換：以前からの関数。ASCIIは半角のままになる点に注意） ---
def to_zenkaku(s: str) -> str:
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", s)

# --- ASCII → 全角（数字・英字・記号・スペースをすべて全角に） ---
def to_zenkaku_wide(s: str) -> str:
    """
    ASCII (0x21-0x7E) を全角に、半角スペース(0x20)は全角スペース(U+3000)に変換。
    他の文字はそのまま。
    """
    if not s:
        return ""
    out = []
    for ch in s:
        oc = ord(ch)
        if ch == " ":
            out.append("\u3000")  # 全角スペース
        elif 0x21 <= oc <= 0x7E:
            out.append(chr(oc + 0xFEE0))  # 全角化（！〜～）
        else:
            out.append(ch)
    return "".join(out)

# --- 丁目/番地/番/号/「の」 → ハイフン寄せ ---
_DEF_REPLACERS = [
    (r"\s+", ""),               # 空白除去（まず詰める）
    (r"丁目", "-"),
    (r"番地", "-"),
    (r"番", "-"),
    (r"号", "-"),
    (r"の", "-"),               # 例: 1の2 → 1-2
    (r"－", "-"),               # 全角記号→半角ハイフン
    (r"[‐‒–—―ｰ−]", "-"),
    (r"-{2,}", "-"),            # 連続ハイフンの圧縮
    (r"(^-|-$)", ""),           # 先頭末尾のハイフン除去
]

def normalize_block_notation(s: str) -> str:
    """
    番地系の表記ゆれを「ハイフン連鎖」に寄せる。
    例: 5丁目25番10号 → 5-25-10 / 1の2 → 1-2
    """
    if not s:
        return ""
    x = to_zenkaku(s)
    for pat, rep in _DEF_REPLACERS:
        x = re.sub(pat, rep, x)
    return x

# --- 建物語辞書ロード ---
def _candidate_paths(path: str | None) -> list[str]:
    c: list[str] = []
    if path:
        c.append(path)
    here = os.path.dirname(os.path.abspath(__file__))   # .../utils
    root = os.path.dirname(here)                         # プロジェクトルート想定
    c.append(os.path.join(root, "data", "bldg_words.json"))
    c.append(os.path.join(here, "bldg_words.json"))     # 開発救済
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
    """
    建物語辞書を読み込む。
    - 旧形式: JSONが配列  -> そのまま語リスト
    - 新形式: {"version": "...", "words": [ ... ]} -> words を返し、内部に版を記録
    見つからない/パース不能の時は [] を返す（呼び出し側がフォールバック）。
    """
    global _BLDG_VERSION
    _BLDG_VERSION = None

    for p in _candidate_paths(path):
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 新形式（オブジェクト）
                if isinstance(data, dict):
                    ver = str(data.get("version") or "").strip() or None
                    words = data.get("words")
                    if isinstance(words, list):
                        _BLDG_VERSION = ver
                        return _dedup_nonempty(words)

                # 旧形式（配列）
                if isinstance(data, list):
                    return _dedup_nonempty(data)
        except Exception:
            continue
    return []

def bldg_words_version() -> str | None:
    """
    直近に load_bldg_words() が読み込んだ辞書のバージョンを返す。
    - 新形式のJSONで 'version' があればその値
    - 旧形式（配列のみ）の場合は None
    """
    return _BLDG_VERSION
