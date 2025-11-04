# utils/kana.py
# ひら→カタカナの簡易変換＋pykakasiがあれば漢字→読みも推定。

import re

def to_katakana_guess(s: str) -> str:
    if not s:
        return ""
    # ひらがな→カタカナ
    hira2kata = str.maketrans({chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)})
    t = s.translate(hira2kata)
    try:
        import pykakasi  # 任意依存
        kks = pykakasi.kakasi()
        res = "".join([r["kana"] for r in kks.convert(s)])
        return res.translate(hira2kata)
    except Exception:
        return t if re.search(r"[ぁ-ん]", s) else ""
