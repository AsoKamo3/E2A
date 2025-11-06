# utils/textnorm.py
# 文字種正規化・番地表記正規化・建物語辞書ロード
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import List

__version__ = "v1.6"
__meta__ = {
    "features": ["to_zenkaku", "normalize_block_notation", "load_bldg_words"],
    "normalize_block_notation": ["丁目/番地/番/号/の → -", "全角記号・空白の整理"],
}

# --- NFKC 全角化 ---
def to_zenkaku(s: str) -> str:
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", s)

# --- 丁目/番地/番/号/「の」 → ハイフン寄せ ---
_DEF_REPLACERS = [
    (r"\s+", ""),               # 空白除去（まず詰める）
    (r"丁目", "-"),
    (r"番地", "-"),
    (r"番", "-"),
    (r"号", "-"),
    (r"の", "-"),               # 例: 1の2 → 1-2
    (r"－", "-"),               # 全角マイナス/ダッシュ類を半角ハイフンに
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
def load_bldg_words(path: str | None = None) -> List[str]:
    """
    data/bldg_words.json を読み込む。
    見つからない/パース不能の時は [] を返す（呼び出し側でフォールバック）。
    """
    candidates = []
    if path:
        candidates.append(path)
    here = os.path.dirname(os.path.abspath(__file__))  # .../utils
    root = os.path.dirname(here)                        # プロジェクトルート想定
    candidates.append(os.path.join(root, "data", "bldg_words.json"))
    candidates.append(os.path.join(here, "bldg_words.json"))  # 開発時の救済

    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    out = [str(w) for w in data if isinstance(w, (str, int, float))]
                    # 重複・空除去
                    seen = set()
                    res = []
                    for w in out:
                        w = str(w).strip()
                        if w and w not in seen:
                            seen.add(w)
                            res.append(w)
                    return res
        except Exception:
            continue
    return []
