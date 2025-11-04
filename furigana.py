# furigana.py
# ふりがな自動付与（推測）をモジュールに分離
# - 環境変数 FURIGANA_ENABLED="1" で有効（デフォルト1）
# - pykakasi が無い場合は自動で簡易置換にフォールバック

import os
import re

def _hira_to_kata(s: str) -> str:
    if not s:
        return ""
    table = {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}  # ぁ-ゖ
    return s.translate(table)

def _guess_simple(s: str) -> str:
    # ひらがな→カタカナのみ（漢字はそのまま・読めなければ空にする方針ならここで調整）
    t = _hira_to_kata(s)
    # かなが一切なければ「読めない」と判断して空欄を返す（元実装と同等の挙動）
    return t if re.search(r"[ぁ-ん]", s) else ""

def to_katakana_guess(s: str) -> str:
    if not s:
        return ""
    enabled = os.environ.get("FURIGANA_ENABLED", "1") == "1"
    if not enabled:
        return ""  # 明示的に無効化

    # pykakasi があれば利用
    try:
        import pykakasi
        kks = pykakasi.kakasi()
        res = "".join([r["kana"] for r in kks.convert(s)])
        return _hira_to_kata(res)
    except Exception:
        # 簡易フォールバック
        return _guess_simple(s)
