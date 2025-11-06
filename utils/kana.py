# utils/kana.py
# かな付与ユーティリティ（常にカタカナで返す） v1.1
from __future__ import annotations

import unicodedata
from typing import List, Tuple

__version__ = "v1.1"

# pykakasi 利用可否を判定
try:
    import pykakasi  # type: ignore
    _KAKASI_AVAILABLE = True
    _kakasi = pykakasi.kakasi()
    # pykakasi はデフォルトでひらがなを返す想定
    _ENGINE_NAME = "pykakasi"
    _ENGINE_DETAIL = ["pykakasi", "pykakasi ok"]
except Exception:
    _KAKASI_AVAILABLE = False
    _kakasi = None  # type: ignore
    _ENGINE_NAME = "fallback"
    _ENGINE_DETAIL = ["fallback", "no pykakasi"]

def engine_name() -> str:
    return _ENGINE_NAME

def engine_detail() -> List[str]:
    return _ENGINE_DETAIL[:]

# --------------------------
# 内部ユーティリティ
# --------------------------
_HIRA_START = ord("ぁ")
_HIRA_END   = ord("ゖ")  # 〻 は含めない
_KATA_OFFSET = ord("ァ") - ord("ぁ")  # 0x30A1 - 0x3041 = 0x60

def _hira_to_kata(s: str) -> str:
    """ひらがな→カタカナ（その他はそのまま）。"""
    out_chars = []
    for ch in s:
        oc = ord(ch)
        if _HIRA_START <= oc <= _HIRA_END:
            out_chars.append(chr(oc + _KATA_OFFSET))
        else:
            out_chars.append(ch)
    return "".join(out_chars)

def _to_fullwidth(s: str) -> str:
    """半角カナ等を含む文字列を NFKC で全角寄せ。"""
    return unicodedata.normalize("NFKC", s or "")

def _is_japanese_text(s: str) -> bool:
    """漢字/かなを1文字でも含むかの簡易判定。"""
    if not s:
        return False
    return any("一" <= ch <= "龥" or "ぁ" <= ch <= "ゟ" or "゠" <= ch <= "ヿ" for ch in s)

# --------------------------
# 公開API
# --------------------------
def to_katakana_guess(s: str) -> str:
    """
    入力文字列 s の読みを推定し、常に『カタカナ（全角）』で返す。
    - pykakasi があれば：漢字/ひらがな/カタカナをひらがな読み化 → カタカナへ変換 → 全角正規化
    - かなしか/英数のみの場合：NFKC した上で、ひらがなはカタカナへ、既存カタカナは全角維持
    注意：
      * 英字の「読み（外来語カナ化）」はここでは行いません（辞書オーバーライドで対応）。
    """
    if not s:
        return ""

    x = str(s)
    # まずは全体をNFKCで正規化（半角カナ→全角など）
    x = _to_fullwidth(x)

    # pykakasi が使え、かつ日本語が含まれるときは読み推定
    if _KAKASI_AVAILABLE and _is_japanese_text(x):
        try:
            # pykakasi.convert は [{'orig':.., 'hira':.., ...}, ...] を返す
            parts = _kakasi.convert(x)  # type: ignore
            hira = "".join(p.get("hira") or p.get("kana") or p.get("orig") or "" for p in parts)
            kata = _hira_to_kata(hira)
            return _to_fullwidth(kata)
        except Exception:
            # 失敗時はフォールバック
            pass

    # フォールバック：既存のかなはカタカナに揃える。英数はそのまま（辞書側で対応）
    return _to_fullwidth(_hira_to_kata(x))
