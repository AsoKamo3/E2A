# converters/address.py
# 日本住所の正規化・分割ロジック
# - normalize_block_notation() で「丁目/番/号/の」をハイフン結合に正規化
# - split_address() が住所1/住所2に分割（v17a: 末尾2ブロックの誤分割を抑止）
# - BLDG_WORDS は utils.textnorm.load_bldg_words() で data/bldg_words.json からロード
#   （見つからない場合は utils.textnorm のデフォルト語彙にフォールバック）
#
# 依存:
#   utils/textnorm.py : to_zenkaku, normalize_block_notation, is_english_only, load_bldg_words

from __future__ import annotations
import re
from typing import Tuple

from utils.textnorm import (
    to_zenkaku,
    normalize_block_notation,
    is_english_only,
    load_bldg_words,
)

ADDR_SPLIT_VERSION = "v17a"  # v17 の最小修正：末尾「数字-数字」誤分割ガード等

# 建物キーワード（data/bldg_words.json を優先。なければ utils.textnorm のデフォルトにフォールバック）
BLDG_WORDS = load_bldg_words()

# 階・室トリガ（出現以降は建物へ寄せる）
FLOOR_ROOM = ["階", "Ｆ", "F", "フロア", "室", "号", "B1", "B2", "Ｂ１", "Ｂ２"]

# 便宜上、ダッシュ/数字の正規表現を共有
_DASH = r"[‐-‒–—―ｰ\-−]"
_NUM = r"[0-9０-９]+"

# 「～内」の扱い（※丸の内などの地名に含まれる単独「内」は誤検出しない）
_INSIDE_TOKENS = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|庁舎内|体育館内|美術館内|博物館内)"


def split_address(addr: str) -> Tuple[str, str]:
    """
    住所文字列を (住所1, 住所2) に分割して返す。
    住所1: 地名～番地（1-2-3 まで／1-2 もあり）
    住所2: 建物名・階・室・「～内」以降など

    v17a での修正点:
      - 正規化後に「… 数字-数字」だけで終わる（建物なし）場合は分割しない早期 return を追加
      - 3ブロック判定時、末尾 tail が「数字だけ」の場合も分割しない（誤って住所2へこぼさない）
    """
    if not addr:
        return "", ""
    s = addr.strip()

    # 1) 「丁目/番(地)/号」「数字の数字」などを '-' に正規化
    s = normalize_block_notation(s)

    # 1-α) 末尾が「数字-数字」だけ（直後に建物語が続かない）→ 分割しない
    #   例: “…1184-31”（建物名なし）を誤って「…1184-3」「1」に割らない
    if re.match(rf"^.*{_NUM}{_DASH}{_NUM}\s*$", s) and not re.search(rf"{_DASH}{_NUM}\s*[^\d０-９]", s):
        return to_zenkaku(s), ""

    # 2) 英文は住所1空欄・全部を住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 3) 「～内」ハンドリング（単独「内」は対象外）
    m_inside = re.search(_INSIDE_TOKENS, s)
    if m_inside:
        left = s[:m_inside.start()]
        right = s[m_inside.start():]
        return to_zenkaku(left), to_zenkaku(right)

    # 4) 「… 数字1-数字2-数字3（-数字4任意）」までを住所1、以降は住所2
    p = re.compile(
        rf"^(?P<base>.*?{_NUM}{_DASH}{_NUM}{_DASH}{_NUM})(?:{_DASH}(?P<room>{_NUM}))?(?P<tail>.*)$"
    )
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = m.group("tail") or ""
        tail_stripped = tail.lstrip()

        # 4-α) tail が「数字だけ」→ 建物なしとみなし分割しない（巻き戻し）
        #      （例: “…1184-31” の末尾 “1” が tail と解釈されても住所2へ送らない）
        if tail_stripped and re.fullmatch(r"[0-9０-９]+", tail_stripped):
            return to_zenkaku(s), ""

        # 5-1) 番地ブロックの直後に空白があり、続きが非数字開始/建物語/階室/「～内」なら建物扱い
        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (
                any(w in tail_stripped for w in BLDG_WORDS)
                or any(t in tail_stripped for t in FLOOR_ROOM)
                or re.search(_INSIDE_TOKENS, tail_stripped)
                or re.match(r"^[^\d０-９]", tail_stripped)
            ):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-2) tail自体に建物語/階室ワードがあれば建物へ
        if tail_stripped and (
            any(w in tail_stripped for w in BLDG_WORDS)
            or any(t in tail_stripped for t in FLOOR_ROOM)
        ):
            return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 5-3) 建物語が base 側に連結（…15桑野ビル2F 等）
        for w in sorted(BLDG_WORDS, key=len, reverse=True):
            idx = base.find(w)
            if idx >= 0:
                return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)

        # 5-4) tail が空でも room があれば住所2へ（…1-2-3-704 等）
        if room:
            return to_zenkaku(base), to_zenkaku(room)

        # 5-5) ここまで来たら建物なし
        return to_zenkaku(s), ""

    # 6) 「数字1-数字2-数字3 + 直結建物」
    p2 = re.compile(rf"^(?P<pre>.*?{_NUM}{_DASH}{_NUM}{_DASH}{_NUM})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # 7) 「数字1-数字2 + 直結建物」
    p3 = re.compile(rf"^(?P<pre>.*?{_NUM}{_DASH}{_NUM})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        return to_zenkaku(m3.group("pre")), to_zenkaku(m3.group("bldg"))

    # 8) スペースでの分割（番地ブロック直後が空白→建物）
    p_space3 = re.compile(rf"^(?P<pre>.*?{_NUM}{_DASH}{_NUM}{_DASH}{_NUM})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg"))

    p_space2 = re.compile(rf"^(?P<pre>.*?{_NUM}{_DASH}{_NUM})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg"))

    # 9) 「～丁目～番～号 + 任意」
    p4 = re.compile(rf"^(?P<pre>.*?{_NUM}丁目{_NUM}番{_NUM}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    # 10) 建物語キーワードの最初の出現位置で二分
    for w in sorted(BLDG_WORDS, key=len, reverse=True):
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 11) 最後の保険：階/室ワードで二分
    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 12) 分割不能 → 住所1に全て
    return to_zenkaku(s), ""
