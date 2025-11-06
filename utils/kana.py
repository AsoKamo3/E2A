# utils/kana.py
# ふりがな自動付与（推測）モジュール v1.1
# - FURIGANA_ENABLED="1" で有効（デフォルト有効）
# - pykakasi があれば使用。最後は必ずカタカナに統一
# - 会社名かな：JSON overrides + 旧WEBアプリ互換の外部辞書（company_dicts / kanji_word_map）をマージ
# - 区切り（／・スペース等）は原文を保持
# - 外部辞書が無くても問題なく動作（フェイルセーフ）

from __future__ import annotations
import os
import re
import json
import unicodedata
import importlib.util
from functools import lru_cache
from typing import Literal, Tuple, Dict, List

__version__ = "v1.1"

# ===== 正規表現・ユーティリティ =====
_RE_HAS_JA     = re.compile(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]")
_RE_HAS_HIRA   = re.compile(r"[ぁ-ん]")
_RE_ASCII_ONLY = re.compile(r"^[\x00-\x7F]+$")
_SPLIT_SEP     = re.compile(r"(／|/|・|,|，|:|：|\(|\)|\[|\]|\{|\}|&|＆|\+|\s|　)")

_HIRA2KATA_TABLE = {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}  # ぁ-ゖ

def ensure_katakana(s: str) -> str:
    if not s:
        return ""
    return s.translate(_HIRA2KATA_TABLE)

def _guess_simple(s: str) -> str:
    if not s:
        return ""
    if _RE_HAS_HIRA.search(s):
        return ensure_katakana(s)
    return ""

def _pykakasi_to_kata(s: str) -> str:
    try:
        import pykakasi  # type: ignore
        kks = pykakasi.kakasi()
        parts = kks.convert(s)
        hira = "".join(p.get("hira", "") or p.get("kana", "") for p in parts)
        return ensure_katakana(hira or "")
    except Exception:
        return _guess_simple(s)

def to_katakana_guess(s: str) -> str:
    if not s:
        return ""
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return ""
    if _RE_ASCII_ONLY.fullmatch(s or ""):
        return ""
    if not _RE_HAS_JA.search(s):
        return ""
    out = _pykakasi_to_kata(s)
    return ensure_katakana(out)

def engine_name() -> Literal["pykakasi", "fallback", "disabled"]:
    if os.environ.get("FURIGANA_ENABLED", "1") != "1":
        return "disabled"
    if not importlib.util.find_spec("pykakasi"):
        return "fallback"
    try:
        import pykakasi  # type: ignore
        _ = pykakasi.kakasi()
        return "pykakasi"
    except Exception:
        return "fallback"

def engine_detail() -> Tuple[str, str]:
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

# ===== 外部辞書のロード（フェイルセーフでオプション対応） =====

@lru_cache(maxsize=1)
def _load_json_overrides() -> Dict[str, str]:
    base_dir = os.path.dirname(os.path.dirname(__file__))  # utils/.. = プロジェクトルート直下想定
    path = os.path.join(base_dir, "data", "company_kana_overrides.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # __version__ キーは無視、値は常にカタカナへ
        return {k: ensure_katakana(v) for k, v in data.items() if k != "__version__"}
    except Exception:
        return {}

@lru_cache(maxsize=1)
def _load_company_except() -> Dict[str, str]:
    # 旧: google2atena/company_dicts.py の COMPANY_EXCEPT を読む（なければ {}）
    spec = importlib.util.find_spec("google2atena.company_dicts")
    if not spec:
        return {}
    try:
        mod = importlib.import_module("google2atena.company_dicts")
        d = getattr(mod, "COMPANY_EXCEPT", {})
        return {str(k): ensure_katakana(str(v)) for k, v in d.items()}
    except Exception:
        return {}

@lru_cache(maxsize=1)
def _load_kanji_word_map() -> Dict[str, str]:
    # 旧: google2atena/kanji_word_map.py の KANJI_WORD_MAP を読む（なければ {}）
    spec = importlib.util.find_spec("google2atena.kanji_word_map")
    if not spec:
        return {}
    try:
        mod = importlib.import_module("google2atena.kanji_word_map")
        d = getattr(mod, "KANJI_WORD_MAP", {})
        return {str(k): ensure_katakana(str(v)) for k, v in d.items()}
    except Exception:
        return {}

def _norm_key(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).lower()

def _apply_kanji_word_map(s: str) -> str:
    """KANJI_WORD_MAP の語を優先置換（長語優先にするため降順ソート）"""
    mapping = _load_kanji_word_map()
    if not mapping or not s:
        return s
    # 長いキーから順に置換
    for k in sorted(mapping.keys(), key=len, reverse=True):
        if k and k in s:
            s = s.replace(k, mapping[k])
    return s

@lru_cache(maxsize=1)
def _merged_overrides() -> Dict[str, str]:
    """
    マージ順（優先度 高→低）:
      1) JSON: data/company_kana_overrides.json（キーは正規化キーで照合するのでここではそのまま）
      2) COMPANY_EXCEPT（google2atena/company_dicts.py）
    キーは NFKC+lower に正規化して保持。
    """
    result: Dict[str, str] = {}
    # 2) COMPANY_EXCEPT
    for k, v in _load_company_except().items():
        result[_norm_key(k)] = ensure_katakana(v)
    # 1) JSON（最優先で上書き）
    for k, v in _load_json_overrides().items():
        result[_norm_key(k)] = ensure_katakana(v)
    return result

def company_kana_from_name(company_name: str) -> str:
    """
    会社名のカナ読み（カタカナ）を返す。
    手順:
      - 区切り記号でトークン分割（区切りは原文維持）
      - 各トークン：
         a) 正規化キー(NFKC+lower)でオーバーライド辞書を検索 → あれば採用
         b) なければ KANJI_WORD_MAP を事前適用してから pykakasi 推測
         c) 推測結果が空（ASCII等）なら NFKC へ寄せてそのまま（※読み不明は無音にしない）
      - 連結してカタカナ統一
    """
    if not company_name:
        return ""
    ov = _merged_overrides()
    parts: List[str] = _SPLIT_SEP.split(company_name)
    out_parts: List[str] = []

    for part in parts:
        if _SPLIT_SEP.fullmatch(part or ""):
            out_parts.append(part)
            continue

        key = _norm_key(part)
        if key in ov:
            out_parts.append(ensure_katakana(ov[key]))
            continue

        # 事前に漢字語マップを適用して読みの安定度を上げる
        pre = _apply_kanji_word_map(part)

        guess = to_katakana_guess(pre)
        if guess:
            out_parts.append(ensure_katakana(guess))
        else:
            # ASCII 等で読み推測しない場合は原文をNFKCしてそのまま残す
            out_parts.append(unicodedata.normalize("NFKC", part))

    return ensure_katakana("".join(out_parts))
