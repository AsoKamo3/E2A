# utils/kana.py
# ふりがな自動付与（推測）モジュール
# - 環境変数 FURIGANA_ENABLED="1" で有効（デフォルト: 有効）
# - pykakasi があれば使用し、無ければ簡易変換（ひら→カタカナ）のみ
# - 他モジュールへの依存なし（循環参照を避ける）

from __future__ import annotations
import os
import re

def _hira_to_kata(s: str) -> str:
    """ひらがな→カタカナ（Unicodeテーブル変換）"""
    if not s:
        return ""
    table = {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}  # ぁ-ゖ
    return s.translate(table)

def _guess_simple(s: str) -> str:
    """
    簡易推測：ひらがな部分のみカタカナ化。
    かなが一切含まれない（＝漢字のみ等）場合は空欄を返す方針。
    """
    if not s:
        return ""
    t = _hira_to_kata(s)
    return t if re.search(r"[ぁ-ん]", s) else ""

def to_katakana_guess(s: str) -> str:
    """
    氏名などの仮名を推測（カタカナ）して返す。
    - FURIGANA_ENABLED が "1" 以外なら空文字を返す（無効化）
    - pykakasi が導入されていればそれを用いて変換
    - 失敗/未導入時はひら→カタカナの簡易変換にフォールバック
    """
    if not s:
        return ""
    enabled = os.environ.get("FURIGANA_ENABLED", "1") == "1"
    if not enabled:
        return ""  # 明示的に無効化（管理しやすさ優先）

    # pykakasi がある場合は利用（例外は安全に握りつぶしてフォールバック）
    try:
        import pykakasi  # type: ignore
        kks = pykakasi.kakasi()
        # pykakasi は文字列を分割して dict リストを返す
        kana = "".join(part.get("kana", "") for part in kks.convert(s))
        return _hira_to_kata(kana)
    except Exception:
        # 簡易フォールバック
        return _guess_simple(s)
