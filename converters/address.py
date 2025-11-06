# converters/address.py
# 住所分割（辞書＋長語優先＋正規化 NFKC+lower）
from __future__ import annotations

import re
import unicodedata
from typing import Tuple, List

from utils.textnorm import to_zenkaku, normalize_block_notation, load_bldg_words, bldg_words_version

__version__ = "v17g"  # v17f→v17g: 住所2の先頭ダッシュ/空白を安全に除去（例: "-ネコノスビル" → "ネコノスビル"）
__meta__ = {
    "strategy": "dict+longest-first+nfkc+lower",
    "dict_version": None,
}

FLOOR_ROOM = ["階", "Ｆ", "F", "フロア", "室", "号", "B1", "B2", "Ｂ１", "Ｂ２"]

try:
    _WORDS: List[str] = load_bldg_words()
    __meta__["dict_version"] = bldg_words_version()
    if not _WORDS:
        raise RuntimeError("empty bldg list")
except Exception:
    _WORDS = ["ビル","タワー","センター","構内","ハイツ","マンション","駅","放送センター","プレステージ"]
    __meta__["dict_version"] = "fallback-minimal"

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").lower()

_BLDG_DICT = sorted({ _norm(w): w for w in _WORDS }.keys(), key=len, reverse=True)

def _find_bldg_pos_norm(s: str) -> int:
    sn = _norm(s)
    for w in _BLDG_DICT:
        pos = sn.find(w)
        if pos >= 0:
            return pos
    return -1

def _has_any_token(s: str, tokens: List[str]) -> bool:
    s = s or ""
    return any(t in s for t in tokens)

_DASHES = " -‐-‒–—―ｰ−－"

def _clean_right(s: str) -> str:
    """住所2側の先頭に紛れ込んだダッシュ/空白を除去して全角化。"""
    if not s:
        return ""
    return to_zenkaku(s.lstrip(_DASHES))

def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and re.search(r"[A-Za-z]", addr)

def split_address(addr: str) -> Tuple[str, str]:
    if not addr:
        return "", ""
    s_orig = addr.strip()

    # 早期分岐：「…1-2-3 ␣ 10F/１０F/10階/10号 …」はここで確定
    dash = r"[‐\-‒–—―ｰ−－]"
    num  = r"[0-9０-９]+"
    pre_3block_floor = re.compile(
        rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})\s+(?P<fr>{num}\s*(?:F|Ｆ|階|号).*)$"
    )
    m_pre = pre_3block_floor.match(s_orig)
    if m_pre:
        base = m_pre.group("base")
        fr   = m_pre.group("fr").strip()
        return to_zenkaku(base), to_zenkaku(fr)

    s = normalize_block_notation(s_orig)

    if is_english_only(s):
        return "", to_zenkaku(s)

    dash = r"[‐\-‒–—―ｰ−－]"
    num  = r"[0-9０-９]+"

    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = (m.group("tail") or "").strip()

        if tail:
            if _find_bldg_pos_norm(tail) >= 0 or _has_any_token(tail, FLOOR_ROOM) or re.match(r"^[^\d０-９]", tail):
                return to_zenkaku(base), _clean_right((room or "") + tail)

        base_pos = _find_bldg_pos_norm(base)
        if base_pos > 0:
            return to_zenkaku(base[:base_pos]), _clean_right(base[base_pos:] + (room or "") + ((" " + tail) if tail else ""))

        if room:
            return to_zenkaku(base), to_zenkaku(room)

        return to_zenkaku(s), ""

    p2_end = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})$")
    m2_end = p2_end.match(s)
    if m2_end:
        return to_zenkaku(m2_end.group("pre")), ""

    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), _clean_right(m2.group("bldg").strip())

    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        pre = m3.group("pre")
        bldg = m3.group("bldg").strip()
        if (_find_bldg_pos_norm(bldg) >= 0) or _has_any_token(bldg, FLOOR_ROOM) or re.match(r"^[^\d０-９]", bldg):
            return to_zenkaku(pre), _clean_right(bldg)
        if re.match(r"^\d", bldg) and re.search(r"(F|Ｆ|階|号)", bldg):
            return to_zenkaku(pre), to_zenkaku(bldg)
        return to_zenkaku(s), ""

    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), _clean_right(m_space3.group("bldg").strip())

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), _clean_right(m_space2.group("bldg").strip())

    pat = r'(?:\d+丁目)?(?:\d+番地|\d+番)?(?:\d+号)?'
    hits = list(re.finditer(pat, s))
    for mm in reversed(hits):
        if re.search(r'\d', mm.group(0)):
            idx = mm.end()
            rest = s[idx:].strip()
            if rest:
                return to_zenkaku(s[:idx]), _clean_right(rest)
            break

    pos = _find_bldg_pos_norm(s)
    if pos > 0:
        return to_zenkaku(s[:pos]), _clean_right(s[pos:])

    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    return to_zenkaku(s), ""
