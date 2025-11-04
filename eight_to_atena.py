# eight_to_atena.py
# ルート直下の薄いラッパ。services/eight_to_atena の公開関数を再エクスポートします。
# 旧関数名 convert_eight_csv_to_atena_csv への互換エイリアスも提供します。

from __future__ import annotations

# 実体は services/eight_to_atena.py にあります
from services.eight_to_atena import (  # type: ignore
    convert_eight_csv_text_to_atena_csv_text,
    ATENA_HEADERS,
    EIGHT_FIXED,
    COMPANY_TYPES,
)

# コンバータ側の内部バージョン（住所分割 v17 系列などの管理に使う想定）
__version__ = "v17"

__all__ = [
    "convert_eight_csv_text_to_atena_csv_text",
    "convert_eight_csv_to_atena_csv",   # 互換エイリアス
    "ATENA_HEADERS",
    "EIGHT_FIXED",
    "COMPANY_TYPES",
    "__version__",
]

# ===== 後方互換のための別名 =====
def convert_eight_csv_to_atena_csv(csv_text: str) -> str:
    """
    旧名互換。内部では convert_eight_csv_text_to_atena_csv_text を呼びます。
    """
    return convert_eight_csv_text_to_atena_csv_text(csv_text)
