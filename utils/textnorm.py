# utils/textnorm.py
# 共通のテキスト正規化・整形ユーティリティ

import os
import re
import json
import unicodedata
from functools import lru_cache

# =========================
# 全角統一
# =========================
def to_zenkaku(s: str) -> str:
    """半角の英数記号／ダッシュ類を全角系に寄せる簡易正規化。"""
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    # ダッシュ系を全角っぽい一本線へ
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)

    def to_wide_char(ch: str) -> str:
        code = ord(ch)
        # 数字
        if 0x30 <= code <= 0x39:
            return chr(code + 0xFEE0)
        # A-Z
        if 0x41 <= code <= 0x5A:
            return chr(code + 0xFEE0)
        # a-z
        if 0x61 <= code <= 0x7A:
            return chr(code + 0xFEE0)
        # 代表的な記号
        table = {
            "/": "／", "#": "＃", "+": "＋", ".": "．", ",": "，", ":": "：",
            "(": "（", ")": "）", "[": "［", "]": "］", "&": "＆", "@": "＠",
            "~": "～", "_": "＿", "'": "’", '"': "”", "%": "％"
        }
        return table.get(ch, ch)

    return "".join(to_wide_char(c) for c in t)

# =========================
# 郵便番号 xxx-xxxx へ
# =========================
def normalize_postcode(s: str) -> str:
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s

# =========================
# 電話番号 正規化＆結合
# =========================
def normalize_phone(*nums):
    cleaned = []
    for n in nums:
        if not n:
            continue
        d = re.sub(r"\D", "", n)
        if not d:
            continue
        # 携帯
        if re.match(r"^(070|080|090)\d{8}$", d):
            cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        # 市外局番 03/04/06（簡略）
        if re.match(r"^(0[346])\d{8}$", d):
            cleaned.append(f"{d[:2]}-{d[2:6]}-{d[6:]}")
            continue
        # その他ざっくり
        if d.startswith("0") and len(d) in (10, 11):
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        cleaned.append(n)
    return ";".join(cleaned)

# =========================
# 「丁目・番・号・の」→ ハイフン正規化
# =========================
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

# =========================
# ふりがな推定（kana.py 側が本体）
# =========================
# → ここではダミーは用意せず、呼び出し側が utils.kana.to_katakana_guess を使う

# =========================
# 部署名の二分割（今回の修正点）
# =========================
def split_department(dept: str):
    """
    Eightの[部署名]を、宛名職人の[部署名1] / [部署名2]に二分する。
    想定セパレータ：
      / ／ | ｜ > ＞ → ⇒ -> → （前後スペースは吸収）
    3パーツ以上は左を多め(ceil(n/2))に寄せ、全角スペースで連結。
    """
    if not dept:
        return "", ""
    sep = r"""
        \s*(?:                # 前後の空白は吸収
            /|／|
            \||｜|
            >|＞|
            →|⇒|
            -\>|→
        )\s*
    """
    parts = [p for p in re.split(sep, dept, flags=re.VERBOSE) if p and p.strip()]
    parts = [p.strip() for p in parts]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) == 2:
        return parts[0], parts[1]
    k = (len(parts) + 1) // 2
    left = "　".join(parts[:k])   # 全角スペース
    right = "　".join(parts[k:])
    return left, right

# =========================
# 建物語辞書のロード（data/bldg_words.json）
# =========================
@lru_cache(maxsize=1)
def load_bldg_words():
    """data/bldg_words.json を読み込む。無ければデフォルト（少数）にフォールバック。"""
    default = [
        "ビル", "マンション", "ハイツ", "レジデンス", "タワー", "スクエア",
        "センター", "ステーション", "プラザ", "コート", "ヒルズ", "プレイス"
    ]
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here)
        path = os.path.join(root, "data", "bldg_words.json")
        with open(path, "r", encoding="utf-8") as f:
            words = json.load(f)
        if isinstance(words, list) and words:
            return words
        return default
    except Exception:
        return default

def get_bldg_words():
    return load_bldg_words()
