# converters/address.py
# 住所分割の実装（辞書＋長語優先＋正規化 NFKC+lower）
from __future__ import annotations

import re
import unicodedata
from typing import Tuple, List

from utils.textnorm import to_zenkaku, normalize_block_notation, load_bldg_words, bldg_words_version

__version__ = "v17f"  # v17e→v17f: 「…1-2-3␣10F」誤連結を早期分岐で是正（他ロジックは不変）
__meta__ = {
    "strategy": "dict+longest-first+nfkc+lower",
    "dict_version": None,   # 起動時に設定
    "notes": [
        "pre-split for '... N-N-N <space> 10F' then proceed as usual",
        "block-notation→hyphen normalize → split",
        "protect trailing 1-2 (avoid false building split)",
        "fallback to minimal markers when dict missing",
    ],
}

# ===== 設定・辞書 =====

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

def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and re.search(r"[A-Za-z]", addr)

def split_address(addr: str) -> Tuple[str, str]:
    if not addr:
        return "", ""
    s_orig = addr.strip()

    # --- (NEW) 早期分岐： "... 数字-数字-数字  ␣  10F/１０F/10Ｆ/１０Ｆ/10階/１０階/10号 ..." を安全に二分
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

    s = s_orig

    # 1) 丁目/番(地)/号/「の」→ハイフン正規化
    s = normalize_block_notation(s)

    # 2) 英文は右側へ
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 正規表現の基本部品（以降は従来どおり）
    dash = r"[‐\-‒–—―ｰ−－]"
    num  = r"[0-9０-９]+"

    # 3) 1-2-3(-4) パターン
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = (m.group("tail") or "").strip()

        if tail:
            if _find_bldg_pos_norm(tail) >= 0 or _has_any_token(tail, FLOOR_ROOM) or re.match(r"^[^\d０-９]", tail):
                return to_zenkaku(base), to_zenkaku((room or "") + tail)

        base_pos = _find_bldg_pos_norm(base)
        if base_pos > 0:
            return to_zenkaku(base[:base_pos]), to_zenkaku(base[base_pos:] + (room or "") + ((" " + tail) if tail else ""))

        if room:
            return to_zenkaku(base), to_zenkaku(room)

        return to_zenkaku(s), ""

    # 4) 「数字-数字」で終わる → 建物扱いしない
    p2_end = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})$")
    m2_end = p2_end.match(s)
    if m2_end:
        return to_zenkaku(m2_end.group("pre")), ""

    # 5) 「数字-数字-数字 + 直結建物」
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg").strip())

    # 6) 「数字-数字 + 直結建物」
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        pre = m3.group("pre")
        bldg = m3.group("bldg").strip()
        if (_find_bldg_pos_norm(bldg) >= 0) or _has_any_token(bldg, FLOOR_ROOM) or re.match(r"^[^\d０-９]", bldg):
            return to_zenkaku(pre), to_zenkaku(bldg)
        if re.match(r"^\d", bldg) and re.search(r"(F|Ｆ|階|号)", bldg):
            return to_zenkaku(pre), to_zenkaku(bldg)
        return to_zenkaku(s), ""

    # 7) スペース分割（番地直後の空白＋建物）
    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg").strip())

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg").strip())

    # 8) 丁目/番/号のブロック（右端で切る）
    pat = r'(?:\d+丁目)?(?:\d+番地|\d+番)?(?:\d+号)?'
    hits = list(re.finditer(pat, s))
    for mm in reversed(hits):
        if re.search(r'\d', mm.group(0)):
            idx = mm.end()
            rest = s[idx:].strip()
            if rest:
                return to_zenkaku(s[:idx]), to_zenkaku(rest)
            break

    # 9) 建物語の最初の出現で二分
    pos = _find_bldg_pos_norm(s)
    if pos > 0:
        return to_zenkaku(s[:pos]), to_zenkaku(s[pos:])

    # 10) 階/室ワードで二分
    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 11) 分割不能 → 住所1に全て
    return to_zenkaku(s), ""
