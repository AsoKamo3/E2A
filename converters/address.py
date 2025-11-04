# converters/address.py
# 役割：住所の前処理（「丁目/番/号/の」→ ハイフン）と、分割ロジック（v17）。
#       建物語辞書は data/bldg_words.json から起動時にロード可能。

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from utils.textnorm import to_zenkaku, is_english_only, normalize_block_notation

SPLIT_LOGIC_VERSION = "v17"

# モジュール内で参照される辞書・語群
BLDG_WORDS: List[str] = []
FLOOR_ROOM = ["階","Ｆ","F","フロア","室","号","B1","B2","Ｂ１","Ｂ２"]

def init_address_module(words_path: Optional[str] = None, words_list: Optional[List[str]] = None) -> None:
    """
    建物語辞書を初期化（ファイル or 直接リスト）。
    失敗しても例外は上げず、空リストで進行（分割は継続）。
    """
    global BLDG_WORDS
    try:
        if words_list is not None:
            BLDG_WORDS = list(words_list)
            return
        if words_path:
            p = Path(words_path)
            if p.exists():
                with p.open("r", encoding="utf-8") as f:
                    BLDG_WORDS = json.load(f)
                return
    except Exception:
        # ログは上位層で必要に応じて
        pass
    # フォールバック（空）
    BLDG_WORDS = []

def _split_core(s: str) -> Tuple[str, str]:
    """
    v17 のコア分割（前処理後の文字列 s を想定）。
    """
    inside_tokens = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|庁舎内|体育館内|美術館内|博物館内)"
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        left = s[:m_inside.start()]
        right = s[m_inside.start():]
        return to_zenkaku(left), to_zenkaku(right)

    dash = r"[‐-‒–—―ｰ\-−]"
    num  = r"[0-9０-９]+"

    # 1) 先頭から 1-2-3（-4任意）まで住所1、以降は住所2
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = (m.group("tail") or "")
        tail_stripped = tail.lstrip()

        # base末尾（…1-2-3）の直後にスペースがあり、後続が非数字で始まるor建物語/階室/insideなら建物扱い
        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (any(w in tail_stripped for w in BLDG_WORDS) or
                any(t in tail_stripped for t in FLOOR_ROOM) or
                re.search(inside_tokens, tail_stripped) or
                re.match(r"^[^\d０-９]", tail_stripped)):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # tail に建物語/階室
        if tail_stripped and (any(w in tail_stripped for w in BLDG_WORDS) or any(t in tail_stripped for t in FLOOR_ROOM)):
            return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        # 建物語が base 側に連結（…15桑野ビル2F）
        for w in sorted(BLDG_WORDS, key=len, reverse=True):
            idx = base.find(w)
            if idx >= 0:
                return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)

        # tail無しでも room があれば住所2（…-704）
        if room:
            return to_zenkaku(base), to_zenkaku(room)

        return to_zenkaku(s), ""

    # 2) 1-2-3 + 直結建物
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # 3) 1-2 + 直結建物
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        return to_zenkaku(m3.group("pre")), to_zenkaku(m3.group("bldg"))

    # 4) スペースで分割（1-2-3 の直後に空白 → 建物）
    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg"))

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg"))

    # 5) ～丁目～番～号 + 任意
    p4 = re.compile(rf"^(?P<pre>.*?{num}丁目{num}番{num}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    # 6) 建物語キーワードで二分
    for w in sorted(BLDG_WORDS, key=len, reverse=True):
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 7) 階/室ワードで二分
    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    return to_zenkaku(s), ""

def split_address(addr: str):
    """
    パブリックAPI：文字列を受け取り→
      1) 丁目/番(地)/号/「の」をハイフン表記へ正規化
      2) 英文なら住所1空欄＋全体を住所2
      3) v17の分割コアへ
    """
    if not addr:
        return "", ""
    s = addr.strip()

    # 丁目・番・号・「の」→ ハイフン正規化
    s = normalize_block_notation(s)

    # 英文は住所1空欄・全部を住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    return _split_core(s)
