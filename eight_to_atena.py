# -*- coding: utf-8 -*-
"""
eight_to_atena.py  v1.1.1  (hotfix: SyntaxError 修正)

Eight の書き出しCSVを「宛名職人」CSVに変換するワンファイルツール。
- 文字コード: UTF-8
- 区切り: カンマ
- 住所1/住所2 は全角統一
- 郵便番号は xxx-xxxx に整形（半角）
- 会社電話は複数候補を ; で結合（スペースなし）
- 部署名はルールに基づき部署名1/部署名2へ分割（全角、＋の前後は全角スペース）
- カスタム列(固定列以降)は「1」の列ヘッダを上から順に メモ1..5、その超過分は 備考1（改行区切り）へ
- “ふりがな”は簡易推定（カタカナ化）*漢字のみ等で推定困難な場合は空欄のまま可
- 会社名かなは法人種別語（株式会社等）は除外して付与
"""

import csv
import re
import sys
import argparse
from pathlib import Path

VERSION = "v1.1.1"

# ---- Eight 側の固定ヘッダ（ここまでが固定列） ----
EIGHT_FIXED_HEADER = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ---- 宛名職人の出力ヘッダ ----
ATENA_HEADER = [
    "姓","名","姓かな","名かな","姓名","姓名かな","ミドルネーム","ミドルネームかな","敬称",
    "ニックネーム","旧姓","宛先","自宅〒","自宅住所1","自宅住所2","自宅住所3","自宅電話",
    "自宅IM ID","自宅E-mail","自宅URL","自宅Social",
    "会社〒","会社住所1","会社住所2","会社住所3","会社電話","会社IM ID","会社E-mail",
    "会社URL","会社Social",
    "その他〒","その他住所1","その他住所2","その他住所3","その他電話","その他IM ID",
    "その他E-mail","その他URL","その他Social",
    "会社名かな","会社名","部署名1","部署名2","役職名",
    "連名","連名ふりがな","連名敬称","連名誕生日",
    "メモ1","メモ2","メモ3","メモ4","メモ5",
    "備考1","備考2","備考3","誕生日","性別","血液型","趣味","性格"
]

# ---- 法人種別（会社名かな から除外）----
CORP_WORDS = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "相互会社", "清算株式会社",
    "一般社団法人", "一般財団法人", "公益社団法人", "公益財団法人",
    "特定非営利活動法人", "ＮＰＯ法人", "中間法人", "有限責任中間法人", "特例民法法人",
    "学校法人", "医療法人", "医療法人社団", "医療法人財団", "宗教法人", "社会福祉法人",
    "国立大学法人", "公立大学法人", "独立行政法人", "地方独立行政法人",
    "特殊法人",
    "有限責任事業組合", "投資事業有限責任組合", "特定目的会社", "特定目的信託"
]

# ---- 全角変換（英数字・記号） ----
ZEN_MAP = str.maketrans(
    {
        **{str(i): chr(ord("０") + i) for i in range(10)},
        **{chr(ord("a")+i): chr(ord("ａ")+i) for i in range(26)},
        **{chr(ord("A")+i): chr(ord("Ａ")+i) for i in range(26)},
        "-": "－", "_": "＿", " ": "　", "/": "／", "#": "＃",
        ".": "．", ",": "，", ":": "：", ";": "；", "&": "＆",
        "(": "（", ")": "）", "[": "［", "]": "］", "'": "’",
        "\"": "”", "+": "＋", "!": "！", "?": "？", "@": "＠",
        "*": "＊"
    }
)

def to_zenkaku(s: str) -> str:
    if not s:
        return s
    return s.translate(ZEN_MAP)

def to_katakana_simple(s: str) -> str:
    if not s:
        return s
    s = re.sub(r'[ぁ-ゖ]', lambda m: chr(ord(m.group(0)) + 0x60), s)
    s = s.encode("utf-8", "ignore").decode("utf-8")
    return s

def strip_corp_words(name: str) -> str:
    s = name or ""
    for w in CORP_WORDS:
        s = s.replace(w, "")
    return s.strip()

def normalize_postal(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return raw

def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"[^\d+]", "", raw)
    m = re.match(r"^(070|080|090)(\d{4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(0[346])(\d{4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(0\d{2})(\d{3,4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw

def join_phones(parts):
    nums = [normalize_phone(p) for p in parts if p and str(p).strip()]
    nums = [n for n in num]()
