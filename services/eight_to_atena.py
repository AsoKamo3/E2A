# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体
# - 列順は ATENA_HEADERS と厳密一致（61列）
# - 住所分割は converters.address.split_address に委譲（分割できなければ (原文, "")）
# - 部署は区切り文字でトークン化し、前半(ceil(n/2))を部署名1、後半を部署名2（全角スペース結合）
# - 姓かな/名かな/姓名かなは現段階では付与しない（空）
# - 電話は「;」連結（スラッシュは置換）
# - CSVのヘッダ・キーは BOM(U+FEFF) と前後空白を除去してから参照
# - 区切りは csv.Sniffer で自動判定（カンマ/タブ両対応）
from __future__ import annotations

import io
import csv
import unicodedata
import math
import re
from typing import List

from converters.address import split_address

__version__ = "v2.19"

ATENA_HEADERS: List[str] = [
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

# Eight 側の固定カラム（この順に存在する想定）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

def _clean_key(k: str) -> str:
    return (k or "").lstrip("\ufeff").strip()

def _clean_row(row: dict) -> dict:
    return {_clean_key(k): (v or "") for k, v in row.items()}

def _to_zenkaku(s: str) -> str:
    if not s:
        return s
    return unicodedata.normalize("NFKC", s)

# 区切り集合：／ / ・ ， 、 ｜ | 半角/全角スペース
SEP_PATTERN = re.compile(r'(?:／|/|・|,|、|｜|\||\s)+')

def _split_department_half(s: str) -> tuple[str, str]:
    """
    部署名をトークン化 → 前半（ceil(n/2)）を部署名1、後半を部署名2。
    結合は全角スペース。
    """
    s = (s or "").strip()
    if not s:
        return "", ""
    tokens = [t for t in SEP_PATTERN.split(s) if t]
    if len(tokens) <= 1:
        return _to_zenkaku(s), ""
    n = len(tokens)
    k = math.ceil(n / 2.0)  # 前半のサイズ
    left = "　".join(tokens[:k])
    right = "　".join(tokens[k:]) if k < n else ""
    return _to_zenkaku(left), _to_zenkaku(right)

def _normalize_postcode(z: str) -> str:
    return (z or "").replace("-", "").strip()

def _normalize_phone(*nums: str) -> str:
    parts = [p.strip() for p in nums if p and p.strip()]
    joined = ";".join(parts)
    # 念のためスラッシュ区切りを矯正
    return joined.replace(" / ", ";").replace("/", ";")

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    Eight のCSV/TSVテキスト → 宛名職人CSVテキスト（61列）
    - 区切りは Sniffer で自動判定（カンマ/タブ）
    """
    buf = io.StringIO(csv_text)
    sample = buf.read(4096)
    buf.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t"])
    except Exception:
        # フォールバックはカンマ
        class _D: delimiter = ","
        dialect = _D()
    reader = csv.DictReader(buf, dialect=dialect)
    # ヘッダ正規化
    reader.fieldnames = [_clean_key(h) for h in (reader.fieldnames or [])]

    rows_out: List[List[str]] = []

    for raw in reader:
        row = _clean_row(raw)
        g = lambda k: (row.get(_clean_key(k), "") or "").strip()

        # 入力
        company_raw = g("会社名")
        dept_raw    = g("部署名")
        title_raw   = g("役職")
        last        = g("姓")
        first       = g("名")
        email       = g("e-mail")
        postcode    = _normalize_postcode(g("郵便番号"))
        addr_raw    = g("住所")
        tel_company = g("TEL会社")
        tel_dept    = g("TEL部門")
        tel_direct  = g("TEL直通")
        fax         = g("Fax")
        mobile      = g("携帯電話")
        url         = g("URL")

        # 住所（まず住所1に原文。分割できた時だけ上書き）
        a1, a2 = split_address(addr_raw)
        if (a2 or "").strip():
            addr1, addr2 = a1, a2
        else:
            addr1, addr2 = addr_raw, ""

        # 電話
        phone_join = _normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署（前半/後半）
        dept1, dept2 = _split_department_half(dept_raw)

        # 姓名・かな（かなは空）
        full_name = f"{last}{first}"
        last_kana = ""
        first_kana = ""
        full_name_kana = ""

        # 会社名（全角化）→ 会社名かなは現段階では付与せず空に
        company = _to_zenkaku(company_raw)
        company_kana = ""

        # メモ/備考（固定カラム以降の '1' 系を採用）
        fn_clean = reader.fieldnames or []
        tail_headers = fn_clean[len(EIGHT_FIXED):]
        flags: List[str] = []
        for hdr in tail_headers:
            val = (row.get(hdr, "") or "").strip()
            if val in ("1", "1.0", "TRUE", "True", "true"):
                flags.append(hdr)
        memo = ["", "", "", "", ""]
        biko = ""
        for i, hdr in enumerate(flags):
            if i < 5:
                memo[i] = hdr
            else:
                biko += (("\n" if biko else "") + hdr)

        # 出力整形（61列）
        out_row: List[str] = [
            # 1..12
            last, first,
            last_kana, first_kana,
            full_name, full_name_kana,
            "", "", "",
            "", "", "",

            # 13..21 自宅
            "", "", "", "", "",
            "", "", "", "",

            # 22..30 会社
            postcode, addr1, addr2, "",
            phone_join, "", email,
            url, "",

            # 31..39 その他
            "", "", "", "", "", "", "", "", "",

            # 40..48 会社名/部署/役職/連名
            company_kana, company,
            dept1, dept2,
            _to_zenkaku(title_raw),
            "", "", "", "",

            # 49..56 メモ/備考
            memo[0], memo[1], memo[2], memo[3], memo[4],
            biko, "", "",

            # 57..61 個人属性
            "", "", "", "", ""
        ]

        if len(out_row) != len(ATENA_HEADERS):
            raise ValueError(f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}")

        rows_out.append(out_row)

    # CSV書き出し
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return out.getvalue()
