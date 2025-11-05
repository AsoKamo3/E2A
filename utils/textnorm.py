# utils/textnorm.py
# 共通テキスト正規化ユーティリティ
# - 全角統一、郵便/電話正規化、部署分割、英語住所判定
# - 建物語辞書のロード
# - 丁目/番/号/「の」→ハイフン正規化（方式Bで正式採用）

from __future__ import annotations
import os
import re
import json
import unicodedata
from typing import List

__all__ = [
    "to_zenkaku",
    "normalize_postcode",
    "normalize_phone",
    "split_department",
    "is_english_only",
    "normalize_block_notation",
    "load_bldg_words",
    "get_bldg_words",
    "FLOOR_ROOM",
]

# =========================
# 全角統一
# =========================
def to_zenkaku(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    # ダッシュ類を全角「－」に寄せる
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)

    def to_wide_char(ch: str) -> str:
        code = ord(ch)
        if 0x30 <= code <= 0x39:  # 0-9
            return chr(code + 0xFEE0)
        if 0x41 <= code <= 0x5A:  # A-Z
            return chr(code + 0xFEE0)
        if 0x61 <= code <= 0x7A:  # a-z
            return chr(code + 0xFEE0)
        table = {
            "/": "／", "#": "＃", "+": "＋", ".": "．", ",": "，", ":": "：",
            "(": "（", ")": "）", "[": "［", "]": "］", "&": "＆", "@": "＠",
            "~": "～", "_": "＿", "'": "’", '"': "”", "%": "％"
        }
        return table.get(ch, ch)

    return "".join(to_wide_char(c) for c in t)

# =========================
# 郵便番号 xxx-xxxx
# =========================
def normalize_postcode(s: str) -> str:
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s

# =========================
# 電話番号正規化・結合
# =========================
def normalize_phone(*nums) -> str:
    cleaned: List[str] = []
    for n in nums:
        if not n:
            continue
        d = re.sub(r"\D", "", n)
        if not d:
            continue
        if re.match(r"^(070|080|090)\d{8}$", d):  # 携帯
            cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        if re.match(r"^(0[346])\d{8}$", d):       # 03/04/06
            cleaned.append(f"{d[:2]}-{d[2:6]}-{d[6:]}")
            continue
        if d.startswith("0") and len(d) in (10, 11):  # その他
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        cleaned.append(n)
    return ";".join(cleaned)

# =========================
# 部署 2 分割（全角スペース結合）
# =========================
def split_department(dept: str):
    if not dept:
        return "", ""
    parts = re.split(r"[\/>＞]|[\s　]*>[>\s　]*|[\s　]*\/[\s　]*|[\s　]*\|[\s　]*", dept)
    parts = [p for p in (p.strip() for p in parts) if p]
    if not parts:
        return to_zenkaku(dept), ""
    n = len(parts)
    k = (n + 1) // 2
    left = "　".join(to_zenkaku(p) for p in parts[:k])
    right = "　".join(to_zenkaku(p) for p in parts[k:])
    return left, right

# =========================
# 英文住所判定
# =========================
def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    # 日本語系の文字が無く、英字が含まれている場合に英文扱い
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and bool(re.search(r"[A-Za-z]", addr))

# =========================
# 丁目/番/号/「の」→ ハイフン正規化（方式B）
# =========================
def normalize_block_notation(s: str) -> str:
    """
    住所分割の“前段”で行うブロック表記の正規化。
    - [数字]丁目[数字]番地[数字]号 → [数字]-[数字]-[数字]
    - [数字]丁目[数字]番[数字]号   → [数字]-[数字]-[数字]
    - [数字]丁目[数字]番地         → [数字]-[数字]
    - [数字]丁目[数字]番           → [数字]-[数字]
    - [数字]の[数字]               → [数字]-[数字]
    """
    if not s:
        return s
    znum = r"[0-9０-９]+"
    # 長いパターン→短いパターンの順で置換
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番\s*({znum})\s*号",   r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地",                 r"\1-\2",   s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番(?!地)",             r"\1-\2",   s)
    s = re.sub(rf"({znum})\s*の\s*({znum})",                          r"\1-\2",   s)
    return s

# =========================
# 建物語辞書のロード
# =========================
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
    "レジデンス","構内","倉庫",
]

_FLOOR_ROOM = ["階","Ｆ","F","フロア","室","号","B1","B2","Ｂ１","Ｂ２"]

_BLDG_WORDS_CACHE: List[str] | None = None

def load_bldg_words(json_path: str = "data/bldg_words.json") -> List[str]:
    """
    data/bldg_words.json をロード。失敗時はデフォルトにフォールバック。
    """
    global _BLDG_WORDS_CACHE
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            _BLDG_WORDS_CACHE = data
        else:
            _BLDG_WORDS_CACHE = _DEFAULT_BLDG_WORDS
    except Exception:
        _BLDG_WORDS_CACHE = _DEFAULT_BLDG_WORDS
    return _BLDG_WORDS_CACHE

def get_bldg_words() -> List[str]:
    """キャッシュ（未ロードならデフォルト）を返す。"""
    global _BLDG_WORDS_CACHE
    return _BLDG_WORDS_CACHE or _DEFAULT_BLDG_WORDS

# エクスポート用（住所分割側でインポートして使う）
FLOOR_ROOM = _FLOOR_ROOM
