# converters/address.py
# 住所の正規化・分割（v17）
# ・「丁目/番(地)/号」「数字の数字」をハイフン化 → 既存の番地分割ロジックへ
# ・「～内」は地名の「内」を誤検知しないように限定（構内/NHK内などのみ）
# ・BLDGワードは data/bldg_words.json をロード。見つからなければ既定語でフォールバック。
# ・必要に応じてホットリロード関数 reload_bldg_words() を提供。

import json
import re
from pathlib import Path
from typing import List, Tuple
from utils.textnorm import to_zenkaku

# ===== 建物キーワードのロード =====
_DEFAULT_BLDG_WORDS = [
    "ANNEX","Bldg","BLDG","Bldg.","BLDG.","CABO","MRビル","Tower","TOWER",
    "Trestage","アーバン","アネックス","イースト","ヴィラ","ウェスト","エクレール",
    "オフィス","オリンピア","ガーデン","ガーデンタワー","カミニート","カレッジ",
    "カンファレンス","キャッスル","キング","クルーセ","ゲート","ゲートシティ","コート",
    "コープ","コーポ","サウス","シティ","シティタワー","シャトレ","スクウェア","スクエア",
    "スタジアム","スタジアムプレイス","ステーション","センター","セントラル","ターミナル",
    "タワー","タワービル","テラス","ドーム","ドミール","トリトン","ノース","パーク",
    "ハイツ","ハウス","パルテノン","パレス","ビル","ヒルズ","ビルディング","フォレスト",
    "プラザ","プレイス","プレステージュ","フロント","ホームズ","マンション","レジデンシャル",
    "レジデンス","構内","倉庫"
]

_BLDG_WORDS: List[str] = _DEFAULT_BLDG_WORDS[:]   # 実働リスト
_FLOOR_ROOM = ["階","Ｆ","F","フロア","室","号","B1","B2","Ｂ１","Ｂ２"]

# data/bldg_words.json を試行読み込み
def _default_data_dir() -> Path:
    # app.py からの相対: project/ 直下
    return Path(__file__).resolve().parents[1] / "data"

def load_bldg_words_from_json(path: Path = None) -> List[str]:
    global _BLDG_WORDS
    if path is None:
        path = _default_data_dir() / "bldg_words.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        words = data.get("words", [])
        if isinstance(words, list) and words:
            _BLDG_WORDS = list(map(str, words))
        return _BLDG_WORDS
    except Exception:
        # JSONが見つからない/壊れている場合は既定語
        _BLDG_WORDS = _DEFAULT_BLDG_WORDS[:]
        return _BLDG_WORDS

# アプリ起動時に一度だけロードを試行
load_bldg_words_from_json()

def reload_bldg_words() -> int:
    """外部UIなどからのホットリロード用"""
    load_bldg_words_from_json()
    return len(_BLDG_WORDS)

# ===== 丁目/番(地)/号/の → ハイフン化 =====
def normalize_block_notation(s: str) -> str:
    if not s:
        return s
    znum = r"[0-9０-９]+"
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番(?!地)", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*の\s*({znum})", r"\1-\2", s)
    return s

def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and bool(re.search(r"[A-Za-z]", addr))

# ===== 住所分割（v17） =====
def split_address(addr: str) -> Tuple[str, str]:
    if not addr:
        return "", ""
    s = addr.strip()

    # 1) ブロック表記をハイフンに正規化
    s = normalize_block_notation(s)

    # 2) 英文は全部住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 3) 内部施設の「〜内」だけを建物側へ（丸の内などの地名は除外）
    inside_tokens = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|庁舎内|体育館内|美術館内|博物館内)"
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        return to_zenkaku(s[:m_inside.start()]), to_zenkaku(s[m_inside.start():])

    dash = r"[‐-‒–—―ｰ\-−]"
    num  = r"[0-9０-９]+"

    # 4) 1-2-3(-4) + tail
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = (m.group("tail") or "")
        tail_stripped = tail.lstrip()

        # spaceの後ろが非数字開始＝建物扱い
        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (any(w in tail_stripped for w in _BLDG_WORDS) or
                any(t in tail_stripped for t in _FLOOR_ROOM) or
                re.search(inside_tokens, tail_stripped) or
                re.match(r"^[^\d０-９]", tail_stripped)):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        if tail_stripped and (any(w in tail_stripped for w in _BLDG_WORDS) or any(t in tail_stripped for t in _FLOOR_ROOM)):
            return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        for w in sorted(_BLDG_WORDS, key=len, reverse=True):
            idx = base.find(w)
            if idx >= 0:
                return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)

        if room:
            return to_zenkaku(base), to_zenkaku(room)

        return to_zenkaku(s), ""

    # 5) 1-2-3 + 直結建物
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # 6) 1-2 + 直結建物
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        return to_zenkaku(m3.group("pre")), to_zenkaku(m3.group("bldg"))

    # 7) spaceで分割
    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg"))

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg"))

    # 8) 丁目・番・号 直接表記
    p4 = re.compile(rf"^(?P<pre>.*?{num}丁目{num}番{num}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    # 9) 建物語キーワードの最初の出現で分割
    for w in sorted(_BLDG_WORDS, key=len, reverse=True):
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 10) 最終保険：階/室
    for w in _FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    return to_zenkaku(s), ""
