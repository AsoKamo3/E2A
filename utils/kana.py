# utils/kana.py
# ふりがな自動付与（推測）モジュール v1.0
# - FURIGANA_ENABLED="1" で有効（デフォルト: 有効）
# - pykakasi が使えればそれを利用。失敗時は簡易（ひら→カタカナ）にフォールバック
# - ensure_katakana: ひらがな→カタカナを強制（混在しても最終カタカナ）
# - company_kana_from_name: 会社名専用。NFKC正規化＋小文字化のキーでオーバーライド辞書を適用し、
#   トークン単位で置換してから残りを推測。区切り（／・スペースなど）は原文を保持。
#
# データファイル:
# - data/company_kana_overrides.json : {"キー(正規化済み)": "読み(カタカナ)"} の辞書
#   キーは NFKC + lower 済み。例: "isaribi", "dentsu", "japan", "ニッポン放送" など

from __future__ import annotations
import os
import re
import json
import unicodedata
import importlib.util
from functools import lru_cache
from typing import Literal, Tuple, Dict, List

__version__ = "v1.0"

# 正規表現
_RE_HAS_JA     = re.compile(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]")
_RE_HAS_HIRA   = re.compile(r"[ぁ-ん]")
_RE_ASCII_ONLY = re.compile(r"^[\x00-\x7F]+$")
# 会社名の区切り（キャプチャして keep）
_SPLIT_SEP = re.compile(r"(／|/|・|,|，|・|:|：|\(|\)|\[|\]|\{|\}|&|＆|\+|\s|　)")

# ひら→カタカナ変換テーブル
_HIRA2KATA_TABLE = {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}  # ぁ-ゖ

def ensure_katakana(s: str) -> str:
    """ひらがなをカタカナに（その他はそのまま）。"""
    if not s:
        return ""
    return s.translate(_HIRA2KATA_TABLE)

def _guess_simple(s: str) -> str:
    """簡易推測：ひらがなが含まれていれば ひら→カタカナ。含まれなければ空（誤推測しない）。"""
    if not s:
        return ""
    if _RE_HAS_HIRA.search(s):
        return ensure_katakana(s)
    return ""

def _pykakasi_to_kata(s: str) -> str:
    """pykakasi を使って読み（最終カタカナ）にする。失敗時は簡易フォールバック。"""
    try:
        import pykakasi  # type: ignore
        kks = pykakasi.kakasi()
        parts = kks.convert(s)
        # pykakasi は hira と kana を返す。ひらを優先取得し、最後にカタカナへ統一。
        hira = "".join(p.get("hira", "") or p.get("kana", "") for p in parts)
        return ensure_katakana(hira or "")
    except Exception:
        return _guess_simple(s)

def to_katakana_guess(s: str) -> str:
    """
    カタカナの読みを推測して返す。
    - FURIGANA_ENABLED != "1" → ""（無効）
    - ASCII のみ / 日本語文字が無い → ""（誤推測しない）
    - pykakasi があれば使用、無ければ簡易
    - 最終的に ensure_katakana でカタカナに統一
    """
    if not s:
        return ""
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return ""
    # 純ASCIIは除外（会社名かななどで上書き辞書を使うシナリオに任せる）
    if _RE_ASCII_ONLY.fullmatch(s or ""):
        return ""
    if not _RE_HAS_JA.search(s):
        return ""
    out = _pykakasi_to_kata(s)
    return ensure_katakana(out)

def engine_name() -> Literal["pykakasi", "fallback", "disabled"]:
    """現在のふりがなエンジンの状態を返す。"""
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return "disabled"
    spec = importlib.util.find_spec("pykakasi")
    if not spec:
        return "fallback"
    try:
        import pykakasi  # type: ignore
        _ = pykakasi.kakasi()
        return "pykakasi"
    except Exception:
        return "fallback"

def engine_detail() -> Tuple[str, str]:
    """
    (engine, detail) を返す。
    detail 例:
      ("pykakasi","pykakasi ok")
      ("fallback","pykakasi spec: None")
      ("fallback","pykakasi error: ModuleNotFoundError: ...")
      ("disabled","env FURIGANA_ENABLED!=1")
    """
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return ("disabled", "env FURIGANA_ENABLED!=1")
    spec = importlib.util.find_spec("pykakasi")
    if not spec:
        return ("fallback", "pykakasi spec: None")
    try:
        import pykakasi  # type: ignore
        _ = pykakasi.kakasi()
        return ("pykakasi", "pykakasi ok")
    except Exception as e:
        return ("fallback", f"pykakasi error: {e.__class__.__name__}: {e}")

# ========= 会社名かな：オーバーライド辞書 =========

@lru_cache(maxsize=1)
def _load_company_overrides() -> Dict[str, str]:
    """
    company_kana_overrides.json を読み込む。
    キーは NFKC + lower 済み文字列、値はカタカナ。
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))  # utils/.. = プロジェクトルート直下を想定
    path = os.path.join(base_dir, "data", "company_kana_overrides.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 値は必ずカタカナへ統一
        return {str(k): ensure_katakana(str(v)) for k, v in data.items()}
    except Exception:
        return {}

def _norm_key(s: str) -> str:
    """NFKC → lower で正規化したキー"""
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).lower()

def company_kana_from_name(company_name: str) -> str:
    """
    会社名の読み（カタカナ）を返す。
    1) 会社名の中の英字・ブランド語などはオーバーライド辞書でトークン置換（NFKC+lowerキー）
    2) 残りは通常推測（to_katakana_guess）
    3) 区切り（／・スペースなど）は原文通り保持
    """
    if not company_name:
        return ""
    ov = _load_company_overrides()
    # 区切りを保持しながらトークン分割
    parts: List[str] = _SPLIT_SEP.split(company_name)
    out_parts: List[str] = []

    for part in parts:
        # 区切りはそのまま
        if _SPLIT_SEP.fullmatch(part or ""):
            out_parts.append(part)
            continue

        key = _norm_key(part)
        if key in ov:
            # オーバーライド優先（すでにカタカナ）
            out_parts.append(ov[key])
            continue

        # 上書きが無いトークンは通常推測。ASCIIのみや日本語無しは "" になりがちなので、
        # その場合は原文を NFKC に寄せてから片仮名カナ語に変換する緩い規則を適用してみる。
        guess = to_katakana_guess(part)
        if guess:
            out_parts.append(ensure_katakana(guess))
        else:
            # 例: "co." などは空になりやすいので、原文を NFKC にして残す（読みとしては無音扱いが妥当）
            out_parts.append(unicodedata.normalize("NFKC", part))

    return "".join(out_parts)
