# eight_to_atena.py（ルート）
# 互換ラッパー：実体は services/eight_to_atena.py にあります。
# 以前のコードが "from eight_to_atena import ..." と書いていても動くように、関数/定数を再エクスポートします。

from services.eight_to_atena import (  # 実体からそのまま re-export
    convert_eight_csv_text_to_atena_csv_text,
    convert_eight_csv_to_atena_csv,   # ファイル→ファイル版が services 側にある想定（なければ削除可）
    __version__,                      # 変換ロジック側のバージョン（例：v1.5 / v17 など）
)

__all__ = [
    "convert_eight_csv_text_to_atena_csv_text",
    "convert_eight_csv_to_atena_csv",
    "__version__",
]
