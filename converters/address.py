# -*- coding: utf-8 -*-
"""
Japanese address splitter for E2A.

- Robust to bldg_words.json being either:
  1) {"version": "v1.0.0", "words": ["…", "…"]}  (dict style)
  2) ["…", "…"]                                  (list style / legacy)

- Avoids TypeError by guarding normalization inputs.

Version: v1.0.0
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional, Sequence, Tuple

# モジュールバージョン
__version__ = "v1.0.1"

# NOTE:
#   We only import the utilities we actually use here.
#   normalize_block_notation: 全角/半角混在の「丁目・番・号」などのブロック表記を正規化
#   to_zenkaku: 数字やハイフン等を全角/半角含む文字列を所定の形に寄せる場合に使用（最小限）
from utils.textnorm import load_bldg_words, normalize_block_notation, to_zenkaku


# ----------------------------
# Helper: safe normalizer
# ----------------------------
def _norm(s) -> str:
    """
    Defensive-normalize to ASCII-ish lower for matching.
    Dictなど非strが来ても "" を返して例外を回避します。
    """
    if not isinstance(s, str):
        return ""
    return unicodedata.normalize("NFKC", s).lower()


# ----------------------------
# Load building words (robust)
# ----------------------------
def _load_building_word_set() -> "set[str]":
    raw = load_bldg_words()
    # Accept both dict style and list style
    if isinstance(raw, dict):
        words = raw.get("words", [])
    else:
        words = raw or []
    return { _norm(w) for w in words if isinstance(w, str) and w.strip() }

_BLDG_WORDS = _load_building_word_set()


# ----------------------------
# Basic extractors
# ----------------------------
_POSTCODE_RE = re.compile(r"(\d{3})-?(\d{4})")

def _extract_postcode(s: str) -> Tuple[Optional[str], str]:
    """
    郵便番号(3-4 or 7連続) を抜き出して返す。返り値は (postcode or None, 残りテキスト)
    """
    if not isinstance(s, str):
        return None, ""
    m = _POSTCODE_RE.search(s)
    if not m:
        return None, s
    pc = f"{m.group(1)}-{m.group(2)}"
    head = s[:m.start()]
    tail = s[m.end():]
    return pc, (head + tail).strip()


# ----------------------------
# Heuristic splitter
# ----------------------------
def _split_by_building_keyword(s: str) -> Tuple[str, Optional[str]]:
    """
    住所文字列をビル名などの建物語彙によって二分。
    - 前半: 町域・番地まで
    - 後半: 建物名以降（見つからなければ None）

    検索は NFKC+lower 化して _BLDG_WORDS で最長語一致に近い簡便探索。
    """
    base = s or ""
    if not base.strip():
        return "", None

    lowered = _norm(base)
    # 探索する語の一覧（長いものから見つけたい）
    keys: List[str] = sorted(_BLDG_WORDS, key=lambda x: (-len(x), x))
    for kw in keys:
        if not kw:
            continue
        idx = lowered.find(kw)
        if idx >= 0:
            # 実文字列側の同位置に割り付け
            # NFKCによりインデックスがズレる恐れはあるが、ここでは簡便に find 前後でスライス
            # （誤差が問題になれば、逐語マッピングを導入）
            pos = max(0, idx)
            # 建物語の直前までを住所本体とみなし、以降を建物名として返す
            return base[:pos].rstrip(), base[pos:].lstrip()
    return base, None


def _post_cleanup(s: str) -> str:
    """
    軽い仕上げ（全角空白→半角空白、余分な空白の圧縮、前後空白トリム）。
    """
    if not isinstance(s, str):
        return ""
    t = unicodedata.normalize("NFKC", s)
    # 連続空白を1つへ
    t = re.sub(r"[ \t\u3000]+", " ", t)
    return t.strip()


# ----------------------------
# Public API
# ----------------------------
def split_address(raw: str) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
    """
    与えられた住所文字列を（郵便番号, 住所1, 住所2, 住所3）の4要素に分割して返す。
      - 住所1: 町域・番地まで（normalize_block_notationを適用）
      - 住所2: 建物名等（建物語彙で判定できた場合）
      - 住所3: それ以降（本実装では空のままにするが、将来拡張余地として残置）
    戻り値:
      (postcode or None, addr1, addr2 or None, addr3 or None)

    注意:
      - 本関数は「落ちないこと」を優先し、最小限のヒューリスティクスで分割します。
      - 高精度の町域判定ロジックは別実装に委ね、ここでは建物語彙での二分に留めます。
    """
    # 1) 郵便番号抽出
    postcode, rest = _extract_postcode(raw)

    # 2) ブロック表記の正規化（丁目・番・号など）
    rest = normalize_block_notation(rest)

    # 3) 建物語彙で二分
    head, tail = _split_by_building_keyword(rest)

    # 4) 仕上げ & 最低限の見栄え統一（番地など数字の全角/半角混在を吸収したい場合は to_zenkaku 併用）
    addr1 = _post_cleanup(head)
    addr2 = _post_cleanup(tail) if tail else None
    addr3 = None  # ここは将来的拡張用

    # 5) 住所1が空なら、残りを全部住所1に入れて落ちないようにする
    if not addr1 and (addr2 or ""):
        addr1, addr2 = (addr2 or ""), None

    # 6) 最終的に to_zenkaku を軽く当てる（半角ハイフンなどが混じっても体裁が揃いやすい）
    addr1 = to_zenkaku(addr1) if addr1 else ""
    if addr2:
        addr2 = to_zenkaku(addr2)

    return (postcode, addr1, addr2, addr3)
