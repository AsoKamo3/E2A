# utils/textnorm.py
# 住所以外でも使える共通ユーティリティ群。

import re
import unicodedata

def to_zenkaku(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)  # ダッシュ類を全角ハイフン風に統一
    def to_wide_char(ch):
        code = ord(ch)
        if 0x30 <= code <= 0x39:  # 0-9
            return chr(code + 0xFEE0)
        if 0x41 <= code <= 0x5A:  # A-Z
            return chr(code + 0xFEE0)
        if 0x61 <= code <= 0x7A:  # a-z
            return chr(code + 0xFEE0)
        table = {
            "/":"／", "#":"＃", "+":"＋", ".":"．", ",":"，", ":":"：",
            "(": "（", ")":"）", "[":"［", "]":"］", "&":"＆", "@":"＠",
            "~":"～", "_":"＿", "'":"’", '"':"”", "%":"％"
        }
        return table.get(ch, ch)
    return "".join(to_wide_char(c) for c in t)

def normalize_postcode(s: str) -> str:
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s

def normalize_phone(*nums):
    cleaned = []
    for n in nums:
        if not n:
            continue
        d = re.sub(r"\D", "", n)
        if not d:
            continue
        if re.match(r"^(070|080|090)\d{8}$", d):  # 携帯
            cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        if re.match(r"^(0[346])\d{8}$", d):       # 03/04/06 系
            cleaned.append(f"{d[:2]}-{d[2:6]}-{d[6:]}")
            continue
        if d.startswith("0") and len(d) in (10,11):
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        cleaned.append(n)
    return ";".join(cleaned)

def split_department(dept: str):
    if not dept:
        return "", ""
    parts = re.split(r"[\/>＞＞＞＞]|[\s　]*>[>\s　]*|[\s　]*\/[\s　]*|[\s　]*\|[\s　]*", dept)
    parts = [p for p in (p.strip() for p in parts) if p]
    if not parts:
        return to_zenkaku(dept), ""
    n = len(parts)
    k = (n + 1) // 2
    left = "　".join(to_zenkaku(p) for p in parts[:k])
    right = "　".join(to_zenkaku(p) for p in parts[k:])
    return left, right

def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    return not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr) and re.search(r"[A-Za-z]", addr)

def normalize_block_notation(s: str) -> str:
    """
    「丁目/番(地)/号」「の」をハイフン連結へ正規化。
    長いパターン優先で置換し、過剰変換を避ける。
    """
    if not s:
        return s
    znum = r"[0-9０-９]+"
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番(?!地)", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*の\s*({znum})", r"\1-\2", s)
    return s
