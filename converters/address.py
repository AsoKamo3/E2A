# converters/address.py
# 住所分割の実装（辞書＋長語優先＋正規化 NFKC+lower）
from __future__ import annotations

import re
import unicodedata
from typing import Tuple, List

from utils.textnorm import to_zenkaku, normalize_block_notation, load_bldg_words

__version__ = "v17d"  # v17cを拡張：辞書＋長語優先＋正規化を明示
__meta__ = {
    "strategy": "dict+longest-first+nfkc+lower",
    "notes": [
        "block-notation→hyphen normalize → split",
        "protect trailing 1-2 (avoid false building split)",
        "fallback to minimal markers when dict missing",
    ],
}

# ===== 設定・辞書 =====

# 階・室トリガ（出現以降は建物側へ寄せる）
FLOOR_ROOM = ["階", "Ｆ", "F", "フロア", "室", "号", "B1", "B2", "Ｂ１", "Ｂ２"]

# 建物語辞書（JSONから読込。空/失敗時は最小セットでフォールバック）
try:
    _WORDS: List[str] = load_bldg_words()
    if not _WORDS:
        raise RuntimeError("empty bldg list")
except Exception:
    _WORDS = ["ビル","タワー","センター","構内","ハイツ","マンション","駅","放送センター","プレステージ"]

def _norm(s: str) -> str:
    """NFKC + lower に正規化"""
    return unicodedata.normalize("NFKC", s or "").lower()

# 正規化済み・重複除去・長語優先の探索配列
_BLDG_DICT = sorted({ _norm(w): w for w in _WORDS }.keys(), key=len, reverse=True)

# ===== ユーティリティ =====

def _find_bldg_pos_norm(s: str) -> int:
    """正規化（NFKC+lower）文字列上で建物語の先頭位置を返す（無ければ -1）。"""
    sn = _norm(s)
    for w in _BLDG_DICT:   # 長い語から
        pos = sn.find(w)
        if pos >= 0:
            return pos
    return -1

def _has_any_token(s: str, tokens: List[str]) -> bool:
    s = s or ""
    return any(t in s for t in tokens)

# ===== 本体 =====

def is_english_only(addr: str) -> bool:
    """日本語系の文字が無く、英字を含むなら英文扱い。"""
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and re.search(r"[A-Za-z]", addr)

def split_address(addr: str) -> Tuple[str, str]:
    """
    日本住所の分割（住所1=番地まで / 住所2=建物・階室など）
      1) 丁目/番(地)/号/「の」を normalize_block_notation() でハイフン系へ寄せる
      2) 英文は住所2へ全投げ
      3) ハイフン連番（5-25-10[-704]）末尾で切り、右側が建物/階室/非数字始まりなら二分
      4) 「数字-数字」で終わるものは保護（建物扱いしない）
      5) 建物語は NFKC+lower 正規化＋**長語優先**で探索
      6) 分割不能は (全文, "")
    """
    if not addr:
        return "", ""
    s = addr.strip()

    # 1) 丁目/番(地)/号/「の」→ハイフン正規化
    s = normalize_block_notation(s)

    # 2) 英文は右側へ
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 正規表現の基本部品
    dash = r"[‐\-‒–—―ｰ−－]"  # 半角-, 各種ダッシュ, 全角－
    num  = r"[0-9０-９]+"

    # 3) 1-2-3(-4) パターン
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = (m.group("tail") or "").strip()

        # tailが建物語/階室/非数字始まりなら建物寄せ
        if tail:
            if _find_bldg_pos_norm(tail) >= 0 or _has_any_token(tail, FLOOR_ROOM) or re.match(r"^[^\d０-９]", tail):
                return to_zenkaku(base), to_zenkaku((room or "") + tail)

        # base側に建物語が連結（…15ネコノスビル 等）
        base_pos = _find_bldg_pos_norm(base)
        if base_pos > 0:
            return to_zenkaku(base[:base_pos]), to_zenkaku(base[base_pos:] + (room or "") + ((" " + tail) if tail else ""))

        # room だけ（…-704）なら住所2へ
        if room:
            return to_zenkaku(base), to_zenkaku(room)

        # 建物なし
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

    # 6) 「数字-数字 + 直結建物」— 非数字開始/建物語/階室なら建物
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

    # 9) 建物語の最初の出現で二分（NFKC+lowerで探索、原文を切る）
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
