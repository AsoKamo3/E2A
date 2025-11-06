# services/eight_to_atena.py
# Eight CSV → 宛名職人CSV 変換本体（I/Oと行マッピング）
# - 列の並びは ATENA_HEADERS と厳密一致（61列）
# - 部署名の 2 分割（utils.textnorm.split_department）
# - 住所分割は converters.address.split_address を使用
# - ふりがな推定は utils.kana（会社名はオーバーライド辞書対応）
#
# v2.28 : ふりがなを必ずカタカナで出力。会社名かなはオーバーライド辞書（company_kana_overrides.json）対応。

from __future__ import annotations

import io
import csv
from typing import List

from converters.address import split_address
from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,
)
from utils.kana import to_katakana_guess, ensure_katakana, company_kana_from_name

__version__ = "v2.28"

# 宛名職人ヘッダ（61列：この順で出力）
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

# 会社種別（かな推定時の「除去」対象。元の会社名そのものは書き換えない）
COMPANY_TYPES = [
    "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]

def _strip_company_type(name: str) -> str:
    base = name or ""
    for t in COMPANY_TYPES:
        base = base.replace(t, "")
    return base

def _company_kana_guess(company_name: str) -> str:
    """
    会社名かなの推定。
    1) 会社種別を除去したベース文字列を得る
    2) company_kana_from_name（オーバーライド辞書＋推測）でカタカナ化
    """
    base = _strip_company_type(company_name or "")
    kana = company_kana_from_name(base)
    return ensure_katakana(kana)

def _iter_extra_flags(fieldnames: List[str], row: dict) -> List[str]:
    """Eight 固定カラム以降で値が '1' のヘッダ名を収集。"""
    flags = []
    tail_headers = fieldnames[len(EIGHT_FIXED):] if fieldnames else []
    for hdr in tail_headers:
        val = (row.get(hdr, "") or "").strip()
        if val == "1":
            flags.append(hdr)
    return flags

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    Eight CSV（UTF-8, カンマ区切り, 1行目ヘッダ）→ 宛名職人 CSV テキスト
    - 出力には ATENA_HEADERS（61列）を必ず含む
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_out: List[List[str]] = []

    for row in reader:
        g = lambda k: (row.get(k, "") or "").strip()

        # --- 入力の取得 ---
        company_raw = g("会社名")
        company     = company_raw
        dept        = g("部署名")
        title       = g("役職")
        last        = g("姓")
        first       = g("名")
        email       = g("e-mail")
        postcode    = normalize_postcode(g("郵便番号"))
        addr_raw    = g("住所")
        tel_company = g("TEL会社")
        tel_dept    = g("TEL部門")
        tel_direct  = g("TEL直通")
        fax         = g("Fax")
        mobile      = g("携帯電話")
        url         = g("URL")

        # --- 住所分割 ---
        addr1, addr2 = split_address(addr_raw)

        # --- 電話の正規化・連結 ---
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # --- 部署 2分割 ---
        dept1, dept2 = split_department(dept)

        # --- 姓名・かな（カタカナ強制） ---
        full_name = f"{last}{first}"
        last_kana  = ensure_katakana(to_katakana_guess(last))
        first_kana = ensure_katakana(to_katakana_guess(first))
        full_name_kana = ensure_katakana(f"{last_kana}{first_kana}") if (last_kana or first_kana) else ""

        # --- 会社名かな（オーバーライド辞書→推測、最終カタカナ） ---
        company_kana = _company_kana_guess(company)

        # --- 空防止 ---
        if not company.strip():
            company = company_raw.strip()

        # --- メモ/備考 ---
        flags = _iter_extra_flags(reader.fieldnames or [], row)
        memo = ["", "", "", "", ""]
        biko = ""
        for i, hdr in enumerate(flags):
            if i < 5:
                memo[i] = hdr
            else:
                biko += (("\n" if biko else "") + hdr)

        # === ここから 61 列を厳密に並べる ===
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
            "", "", "", "", "", "", "", "",

            # 40..48 会社名/部署/役職/連名
            company_kana, company,
            to_zenkaku(dept1), to_zenkaku(dept2),
            to_zenkaku(title),
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

    # --- 書き出し ---
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return buf.getvalue()
