# converters/address.py
# 住所の正規化・分割ロジック（v17b）
from __future__ import annotations

import re
from typing import Tuple, List

from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,   # ここでは未使用だが共通API維持
    normalize_phone,      # ここでは未使用だが共通API維持
    split_department,     # ここでは未使用だが共通API維持
    normalize_block_notation,
    load_bldg_words,      # data/bldg_words.json 読み込み
)

# 建物語辞書をロード
BLDG_WORDS: List[str] = load_bldg_words()

# 階・室トリガ（出現以降は建物へ寄せる）
FLOOR_ROOM = ["階","Ｆ","F","フロア","室","号","B1","B2","Ｂ１","Ｂ２"]

__version__ = "v17b"

def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and re.search(r"[A-Za-z]", addr)

def split_address(addr: str) -> Tuple[str, str]:
    """
    日本住所の分割（住所1=番地まで / 住所2=建物・階室など）
    v17b 修正点:
      - 「1-2 で終わる」ケースを先に確定（末尾アンカー）し、末尾1桁が建物扱いされるバックトラックを防止
    """
    if not addr:
        return "", ""
    s = addr.strip()

    # 1) 丁目/番(地)/号/「の」を '-' に正規化
    s = normalize_block_notation(s)

    # 2) 英文は住所1空欄・全部を住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 3) 「～内」ハンドリング（地名の“内”は除外）
    inside_tokens = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|庁舎内|体育館内|美術館内|博物館内)"
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        left = s[:m_inside.start()]
        right = s[m_inside.start():]
        return to_zenkaku(left), to_zenkaku(right)

    # 4) 可変ハイフン／数字
    dash = r"[‐-‒–—―ｰ\-−－]"  # ※ FULLWIDTH '－' を追加
    num  = r"[0-9０-９]+"

    # 5) 1-2-3(-4) パターン（基本）
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = m.group("tail") or ""
        tail_stripped = tail.lstrip()

        # 5-1) 番地直後のスペース→建物
        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (any(w in tail_stripped for w in BLDG_WORDS) or
                any(t in tail_stripped for t in FLOOR_ROOM) or
                re.search(inside_tokens, tail_stripped) or
                re.match(r"^[^\d０-９]", tail_stripped)):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-2) tail に建物語・階室
        if tail_stripped and (any(w in tail_stripped for w in BLDG_WORDS) or any(t in tail_stripped for t in FLOOR_ROOM)):
            return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-3) base 側に建物語が連結（…15桑野ビル2F 等）
        for w in sorted(BLDG_WORDS, key=len, reverse=True):
            idx = base.find(w)
            if idx >= 0:
                return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)

        # 5-4) tail が空で room があれば住所2へ（…-704 等）
        if room:
            return to_zenkaku(base), to_zenkaku(room)

        # 5-5) 建物なし
        return to_zenkaku(s), ""

    # 6) ★追加：純粋な「1-2 で終わる」ケースは丸ごと住所1に確定（ここが v17b の要点）
    p2_end = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})$")  # 末尾アンカー
    m2_end = p2_end.match(s)
    if m2_end:
        return to_zenkaku(m2_end.group("pre")), ""

    # 7) 「数字1-数字2-数字3 + 直結建物」
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # 8) 「数字1-数字2 + 直結建物」※ここは“建物が確実に続く”場合に限定したい
    #    - 直後が空白/建物語/階室/「～内」/記号など“番地の続きではない”兆候を期待
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>(?:[\s　].+|(?:.+)))$")
    # ただし、誤分割抑止のため、ここに来る前に p2_end で「末尾」ケースを除外済み
    m3 = p3.match(s)
    if m3:
        pre = m3.group("pre")
        bldg = m3.group("bldg")
        bldg_stripped = bldg.lstrip()
        # “建物・階室など”の兆候があるかを確認（なければ誤分割の可能性）
        if (any(w in bldg_stripped for w in BLDG_WORDS) or
            any(t in bldg_stripped for t in FLOOR_ROOM) or
            re.search(inside_tokens, bldg_stripped) or
            re.match(r"^[^\d０-９]", bldg_stripped)):   # 非数字開始
            return to_zenkaku(pre), to_zenkaku(bldg_stripped)
        # 数字開始（例: "3F" 等）の可能性：F/階/号 へ続くなら建物扱い
        if re.match(r"^\d", bldg_stripped) and re.search(r"(F|Ｆ|階|号)", bldg_stripped):
            return to_zenkaku(pre), to_zenkaku(bldg_stripped)
        # それ以外は誤分割の可能性が高いので、全体を住所1へ戻す
        return to_zenkaku(s), ""

    # 9) スペースでの分割（番地ブロック直後が空白→建物）
    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg"))

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg"))

    # 10) 「～丁目～番～号 + 任意」
    p4 = re.compile(rf"^(?P<pre>.*?{num}丁目{num}番{num}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    # 11) 建物語キーワードの最初の出現位置で二分
    for w in sorted(BLDG_WORDS, key=len, reverse=True):
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 12) 最後の保険：階/室ワードで二分
    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 13) 分割不能 → 住所1に全て
    return to_zenkaku(s), ""
