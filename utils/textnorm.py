# -*- coding: utf-8 -*-
# utils/textnorm.py v1.16
# 文字種正規化・番地表記正規化・辞書ロード＆辞書バージョン問い合わせ
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import List, Any, Optional

__version__ = "v1.16"
__meta__ = {
    "features": [
        "to_zenkaku (NFKC)",
        "to_zenkaku_wide (ASCII→全角：数字/英字/記号/スペース)",
        "normalize_block_notation",
        "normalize_postcode (###-####・不正は空)",
        "load_bldg_words (array or {version,words})",
        "bldg_words_version()",
        "corp_terms_version()",
        "company_overrides_version()",
    ],
}

# 内部保持用バージョンキャッシュ
_BLDG_VERSION: Optional[str] = None
_CORP_TERMS_VERSION: Optional[str] = None
_COMPANY_OVERRIDES_VERSION: Optional[str] = None

# ----------------------------
# 基本正規化
# ----------------------------
def to_zenkaku(s: str) -> str:
    """NFKC 正規化（None 安全化）。"""
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", s)

def to_zenkaku_wide(s: str) -> str:
    """
    ASCII 可視文字(0x21-0x7E)とスペースを『全角』に寄せる。
    例: "ABC 12-3" → "ＡＢＣ　１２－３"
    """
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

# ----------------------------
# 郵便番号・ブロック表記
# ----------------------------
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

# デフォルト置換ルール（丁目・番地・番・号・の・各種ダッシュ等）
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
    """町丁目・番地・号などのブロック表記をハイフン連結へ寄せる簡易正規化。"""
    if not s:
        return ""
    x = to_zenkaku(s)
    for pat, rep in _DEF_REPLACERS:
        x = re.sub(pat, rep, x)
    return x

# ----------------------------
# data/bldg_words.json 読み込み
# ----------------------------
def _candidate_paths(path: str | None, filename: str) -> list[str]:
    c: list[str] = []
    if path:
        c.append(path)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    c.append(os.path.join(root, "data", filename))  # /.../data/xxx.json
    c.append(os.path.join(here, filename))          # utils/xxx.json（開発用）
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
    data/bldg_words.json を読み込む。
      - list 形式: ["…","…"]
      - dict 形式: {"version":"v1.0.0","words":[…]}
    """
    global _BLDG_VERSION
    _BLDG_VERSION = None
    for p in _candidate_paths(path, "bldg_words.json"):
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

def bldg_words_version() -> Optional[str]:
    """直近に load_bldg_words() が読み込んだバージョン（dict形式時）を返す。"""
    return _BLDG_VERSION

# ----------------------------
# data/corp_terms.json / data/company_kana_overrides.json のバージョン照会
# ----------------------------
def _load_json_version(filename: str) -> Optional[str]:
    for p in _candidate_paths(None, filename):
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    ver = data.get("version")
                    if isinstance(ver, str) and ver.strip():
                        return ver.strip()
                # list 形式には version が無い想定
        except Exception:
            continue
    return None

def corp_terms_version() -> Optional[str]:
    """data/corp_terms.json の version を返す（無ければ None）。"""
    global _CORP_TERMS_VERSION
    _CORP_TERMS_VERSION = _load_json_version("corp_terms.json")
    return _CORP_TERMS_VERSION

def company_overrides_version() -> Optional[str]:
    """data/company_kana_overrides.json の version を返す（無ければ None）。"""
    global _COMPANY_OVERRIDES_VERSION
    _COMPANY_OVERRIDES_VERSION = _load_json_version("company_kana_overrides.json")
    return _COMPANY_OVERRIDES_VERSION
