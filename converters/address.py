# converters/address.py
# 住所の正規化・分割ロジック（v17c）
# - 丁目/番(地)/号/「の」→ハイフン正規化は utils.textnorm.normalize_block_notation を正式採用
# - 建物語辞書は utils.textnorm.load_bldg_words を使用
# - v17b の修正（「1-2 で終わる」番地を先に終端確定）を維持
from __future__ import annotations

import re
from typing import Tuple, List

from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,   # 他モジュールとのAPI整合のためインポート維持（本ファイル内では未使用）
    normalize_phone,      # 同上
    split_department,     # 同上
    normalize_block_notation,
    load_bldg_words,      # data/bldg_words.json 読み込み
)

# 建物語辞書をロード
BLDG_WORDS: List[str] = load_bldg_words()

# 階・室トリガ（出現以降は建物へ寄せる）
FLOOR_ROOM = ["階", "Ｆ", "F", "フロア", "室", "号", "B1", "B2", "Ｂ１", "Ｂ２"]

__version__ = "v17c"


def is_english_only(addr: str) -> bool:
    """日本語系の文字が無く、英字を含むなら英文扱い。"""
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and re.search(r"[A-Za-z]", addr)


def split_address(addr: str) -> Tuple[str, str]:
    """
    日本住所の分割（住所1=番地まで / 住所2=建物・階室など）

    v17c（= v17bの内容を維持しつつバージョンだけ更新）要点:
      - 「1-2 で終わる」ケースを先に終端アンカーで確定し、末尾1桁が建物扱いに
        “バックトラック”される誤分割を防止
      - ハイフン類に全角 '－' を含めてマッチ精度を上げる
    """
    if not addr:
        return "", ""
    s = addr.strip()

    # 1) 丁目/番(地)/号/「の」を '-' に正規化（分割前処理）
    s = normalize_block_notation(s)

    # 2) 英文は住所1空欄・全部を住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 3) 「～内」ハンドリング（地名の“内”は除外）
    inside_tokens = (
        r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|"
        r"庁舎内|体育館内|美術館内|博物館内)"
    )
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        left = s[: m_inside.start()]
        right = s[m_inside.start() :]
        return to_zenkaku(left), to_zenkaku(right)

    # 4) 可変ハイフン／数字（全角 '－' を含める）
    dash = r"[‐\-‒–—―ｰ−－]"  # 半角-, 各種ダッシュ, 全角－
    num = r"[0-9０-９]+"

    # 5) 1-2-3(-4) パターン（基本）
    p = re.compile(
        rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$"
    )
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = m.group("tail") or ""
        tail_stripped = tail.lstrip()

        # 5-1) 番地直後のスペース→建物
        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (
                any(w in tail_stripped for w in BLDG_WORDS)
                or any(t in tail_stripped for t in FLOOR_ROOM)
                or re.search(inside_tokens, tail_stripped)
                or re.match(r"^[^\d０-９]", tail_stripped)
            ):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-2) tail に建物語・階室
        if tail_stripped and (
            any(w in tail_stripped for w in BLDG_WORDS)
            or any(t in tail_stripped for t in FLOOR_ROOM)
        ):
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

    # 6) 純粋な「1-2 で終わる」ケースは丸ごと住所1に確定（誤分割防止の要）
    p2_end = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})$")  # 末尾アンカーで終端確定
    m2_end = p2_end.match(s)
    if m2_end:
        return to_zenkaku(m2_end.group("pre")), ""

    # 7) 「数字1-数字2-数字3 + 直結建物」
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # 8) 「数字1-数字2 + 直結建物」
    #    直後が“番地の続きではない”兆候（空白/建物語/階室/「～内」/非数字開始など）のときのみ建物扱い
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        pre = m3.group("pre")
        bldg = m3.group("bldg")
        bldg_stripped = bldg.lstrip()
        if (
            any(w in bldg_stripped for w in BLDG_WORDS)
            or any(t in bldg_stripped for t in FLOOR_ROOM)
            or re.search(inside_tokens, bldg_stripped)
            or re.match(r"^[^\d０-９]", bldg_stripped)  # 非数字開始
        ):
            return to_zenkaku(pre), to_zenkaku(bldg_stripped)
        # 数字開始でも F/階/号 を含むなら建物扱い
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
