# utils/textnorm.py
# テキスト正規化ユーティリティ v1.11
# - to_zenkaku: 英数記号スペースも含め全角化（NFKC→可能なら jaconv.z2h の逆で h2z）
# - normalize_postcode: 7桁 → NNN-NNNN（半角）
# - normalize_phone: TEL 正規化（携帯/050/0120/0800/0570/固定）→ 半角ハイフン区切り、';' 連結
# - split_department: 部署名を前半/後半に分割
# - strip_corp_terms: 法人格語の除去（corp_terms.json と内蔵の両方）
# - 各辞書のバージョン問い合わせ（bldg_words_version / corp_terms_version / company_overrides_version）

from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import List, Tuple

# 市外局番辞書（最長一致用）
try:
    from utils.jp_area_codes import AREA_CODES
except Exception:
    AREA_CODES = tuple()

__version__ = "v1.11"

# ========== 全角化 ==========

def _half_to_full_basic(ch: str) -> str:
    # 基本英数記号とスペースを全角化（NFKC では半角→全角にならない文字に対応）
    code = ord(ch)
    # ASCII可視文字
    if 0x21 <= code <= 0x7E:
        return chr(code + 0xFEE0)
    if ch == " ":
        return "　"
    return ch

def to_zenkaku(s: str) -> str:
    if not s:
        return ""
    # まず NFKC で互換正規化 → その後 ASCII を全角化
    t = unicodedata.normalize("NFKC", s)
    t2 = "".join(_half_to_full_basic(c) for c in t)
    # ダッシュ・スラッシュ類は全角へ寄せる
    t2 = t2.replace("-", "－").replace("‐", "－").replace("–", "－").replace("—", "－")
    t2 = t2.replace("/", "／")
    return t2

# ========== 郵便番号 ==========

def normalize_postcode(s: str) -> str:
    """
    - 数字以外を除去 → 7桁なら NNN-NNNN を返す
    - それ以外は空文字（Eight 側の欠損は無理に残さない）
    """
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return ""

# ========== 電話番号 ==========

_MOBILE_PREFIX = ("090","080","070","060")
_SPECIAL_PREFIX = ("050",)      # IP電話
_TOLL_FREE = ("0120","0800")    # フリーダイヤル
_NAVIGATIONAL = ("0570",)       # ナビダイヤル

def _format_mobile(num: str) -> str:
    return f"{num[:3]}-{num[3:7]}-{num[7:]}"  # 3-4-4

def _format_050(num: str) -> str:
    return f"{num[:3]}-{num[3:7]}-{num[7:]}"  # 3-4-4

def _format_0120_0800(num: str) -> str:
    return f"{num[:4]}-{num[4:7]}-{num[7:]}"  # 4-3-3

def _format_0570(num: str) -> str:
    # 0570-000-000 or 0570-00-0000 → 0570-XXX-XXX のどちらもあり得るが 4-3-3 を優先
    return f"{num[:4]}-{num[4:7]}-{num[7:]}"

def _format_fixed_with_area(num: str) -> str:
    """
    固定電話（0始まり10桁）を市外局
