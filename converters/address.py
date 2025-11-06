# converters/address.py
import re
from typing import Tuple, List

# 建物・施設っぽいマーカー（必要なら増やす）
_BUILDING_MARKERS: List[str] = [
    "ビル", "タワー", "センター", "構内", "ハイツ", "マンション",
    "プレステージ", "駅", "放送センター"
]

def split_address(s: str) -> Tuple[str, str]:
    """
    住所を (住所1, 住所2) に分割。
    ルール（いずれかで分割できたら終了）:
      1) ハイフン連番: 5-25-10 のような番地連鎖の末尾までを住所1、後続を住所2
      2) 「丁目/番地/番/号」の連続ブロックの末尾までを住所1、後続を住所2
      3) 上記で切れなければ建物マーカー直前で分割
      4) 上記で切れなければ分割なし => (s, "")
    """
    s = (s or "").strip()
    if not s:
        return "", ""

    # 1) 5-25-10 等（数字-(数字-)数字）
    m = re.search(r'(\d+(?:-\d+){1,3})(.*)$', s)
    if m:
        core, rest = m.group(1), m.group(2).strip()
        if rest:
            left_end = s.index(core) + len(core)
            return s[:left_end], rest

    # 2) 丁目/番地/番/号の連続（右側の一致で切る）
    #   例: 5丁目25番10号 / 5丁目25番 / 5丁目 など
    pat = r'(?:\d+丁目)?(?:\d+番地|\d+番)?(?:\d+号)?'
    hits = list(re.finditer(pat, s))
    for mm in reversed(hits):
        if re.search(r'\d', mm.group(0)):  # 中に数字が含まれている一致のみ有効
            idx = mm.end()
            rest = s[idx:].strip()
            if rest:
                return s[:idx], rest
            break

    # 3) 建物マーカー直前で分割
    for mk in _BUILDING_MARKERS:
        pos = s.find(mk)
        if pos > 0:
            left, right = s[:pos].rstrip(), s[pos:].lstrip()
            if left and right:
                return left, right

    # 4) 分割不能
    return s, ""
