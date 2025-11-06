# utils/kana.py
# ふりがな自動付与（推測）モジュール v0.4
# - 環境変数 FURIGANA_ENABLED="1" で有効（デフォルト: 有効）
# - pykakasi があれば使用し、無ければ簡易変換（ひら→カタカナ）のみ
# - 他モジュールへの依存なし（循環参照回避）
from __future__ import annotations

import os
import re

__version__ = "v0.4"

_HIRA_RE = re.compile(r"[ぁ-ん]")

def _hira_to_kata(s: str) -> str:
    """ひらがな→カタカナ（Unicodeテーブル変換）。その他の文字はそのまま。"""
    if not s:
        return ""
    table = {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}  # ぁ-ゖ
    return s.translate(table)

def _guess_simple(s: str) -> str:
    """
    簡易推測：入力中の「ひらがな部分」をカタカナに置換。
    かなが含まれない（漢字のみ等）の場合は空欄を返す方針。
    """
    if not s:
        return ""
    has_hira = bool(_HIRA_RE.search(s))
    if not has_hira:
        return ""
    return _hira_to_kata(s)

def to_katakana_guess(s: str) -> str:
    """
    氏名などの仮名を推測（カタカナ）して返す。
    - FURIGANA_ENABLED が "1" 以外なら空文字を返す（無効化）
    - pykakasi が導入されていればそれを用いて変換（失敗時は安全にフォールバック）
    - 失敗/未導入時はひら→カタカナの簡易変換にフォールバック
    """
    if not s:
        return ""
    enabled = os.environ.get("FURIGANA_ENABLED", "1") == "1"
    if not enabled:
        return ""  # 明示的に無効化

    # pykakasi がある場合は優先利用
    try:
        import pykakasi  # type: ignore
        kks = pykakasi.kakasi()
        # pykakasi は dict のリストを返す。キー "kana" がひらがな。
        kana = "".join(part.get("kana", "") for part in kks.convert(s))
        return _hira_to_kata(kana) if kana else _guess_simple(s)
    except Exception:
        # 簡易フォールバック
        return _guess_simple(s)
