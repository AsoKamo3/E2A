# utils/kana.py
# ふりがな自動付与の薄いラッパ
# - 実体は utils.textnorm.to_katakana_guess に一本化（重複実装を排除）
# - 環境変数 FURIGANA_ENABLED=“1” で有効（デフォルト1：有効）
# - “0” のときは常に空文字を返す（以前の仕様を踏襲）

import os
from .textnorm import to_katakana_guess as _core_to_katakana_guess

def to_katakana_guess(s: str) -> str:
    """
    かな推定。FURIGANA_ENABLED != '1' の場合は空文字を返す。
    """
    if not s:
        return ""
    enabled = os.environ.get("FURIGANA_ENABLED", "1") == "1"
    if not enabled:
        return ""  # 明示的に無効化
    # 実体は textnorm 側の実装を使用（pykakasiがあれば利用、なければフォールバック）
    return _core_to_katakana_guess(s)
