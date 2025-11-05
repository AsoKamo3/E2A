# converters/address.py
# 住所の正規化・分割ロジック
# - 丁目/番/号/「の」→ハイフン正規化は utils.textnorm.normalize_block_notation を正式採用
# - 建物語辞書は utils.textnorm.load_bldg_words / get_bldg_words を使用
# - 既存の分割戦略（v17）を踏襲しつつ、辞書取得のみ共通化
from __future__ import annotations
import re
from utils.textnorm import (
    to_zenkaku,
    is_english_only,
    normalize_block_notation,   # ★方式B
    get_bldg_words,
    FLOOR_ROOM,
)

ADDRESS_SPLIT_VERSION = "v17b"

# 起動時に app.py 側で load_bldg_words() が呼ばれる前提。
# 未ロードでも get_bldg_words() はデフォルトにフォールバックする。
def _sorted_bldg_words():
    return sorted(get_bldg_words(), key=len, reverse=True)

def split_address(addr: str):
    """
    住所を (住所1, 住所2) に分割して返す。
    - 住所1: 都道府県～番地ブロック（例：... 1-2-3 まで）
    - 住所2: 建物名・階室・「～内」等
    """
    if not addr:
        return "", ""
    s = addr.strip()

    # 1) 丁目・番(地)・号・「の」→ ハイフン正規化（方式B）
    s = normalize_block_notation(s)

    # 2) 英文は住所1空欄で全塊を住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 3) 「～内」系（地名の“内”は除外するため限定語のみ）
    inside_tokens = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|庁舎内|体育館内|美術館内|博物館内)"
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        left = s[:m_inside.start()]
        right = s[m_inside.start():]
        return to_zenkaku(left), to_zenkaku(right)

    # 4) 可変ハイフン/数字
    dash = r"[‐-‒–—―ｰ\-−]"
    num  = r"[0-9０-９]+"

    # 5) 「… 数字1-数字2-数字3（-数字4 任意） + tail」
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = m.group("tail") or ""
        tail_stripped = tail.lstrip()

        # 5-1) 番地直後がスペースで、その後ろが非数字/建物語/階室/「～内」なら建物扱い
        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (any(w in tail_stripped for w in get_bldg_words()) or
                any(t in tail_stripped for t in FLOOR_ROOM) or
                re.search(inside_tokens, tail_stripped) or
                re.match(r"^[^\d０-９]", tail_stripped)):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-2) tail に建物語/階室があれば建物へ
        if tail_stripped and (any(w in tail_stripped for w in get_bldg_words()) or any(t in tail_stripped for t in FLOOR_ROOM)):
            return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-3) 建物語が base 側に直結（…15桑野ビル2F 等）
        for w in _sorted_bldg_words():
            idx = base.find(w)
            if idx >= 0:
                return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)

        # 5-4) tail が空でも room があれば住所2（例：1-2-3-704）
        if room:
            return to_zenkaku(base), to_zenkaku(room)

        # 5-5) 建物なし
        return to_zenkaku(s), ""

    # 6) 「数字1-数字2-数字3 + 直結建物」
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # 7) 「数字1-数字2 + 直結建物」
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        return to_zenkaku(m3.group("pre")), to_zenkaku(m3.group("bldg"))

    # 8) スペースでの分割（番地ブロックの直後が空白→建物）
    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg"))

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg"))

    # 9) 「～丁目～番～号 + 任意」
    p4 = re.compile(rf"^(?P<pre>.*?{num}丁目{num}番{num}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    # 10) 建物語キーワードの最初の出現で二分
    for w in _sorted_bldg_words():
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 11) 最後の保険：階/室ワードで二分
    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 12) 分割不能
    return to_zenkaku(s), ""
