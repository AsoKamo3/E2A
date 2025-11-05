# services/eight_to_atena.py
# Eight CSV → 宛名職人 CSV 変換サービス本体
# 最小修正点: 「その他」ブロック(9列)の不足を1列補完し、ヘッダ(61列)と出力列数を厳密一致
from __future__ import annotations

import io
import csv
from typing import List, Tuple

from converters.address import split_address
from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,
)
from utils.kana import to_katakana_guess

__version__ = "2.2.1"

# 宛名職人ヘッダ（61列）
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

# Eight の固定カラム名（順序は Eight CSV 側に依存）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# 会社種別（かな付与時に除外する語）
COMPANY_TYPES = [
    "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]

def _get(row: dict, key: str) -> str:
    return (row.get(key, "") or "").strip()

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    Eight CSV テキスト → 宛名職人 CSV テキスト
    - 出力は ATENA_HEADERS と 1:1 で 61 列に揃える
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: List[List[str]] = []

    # カスタム列（固定以降の「見出しに '1' が入っているとメモへ」ルール）
    fieldnames = reader.fieldnames or []
    custom_headers = fieldnames[len(EIGHT_FIXED):]

    for row in reader:
        company     = _get(row, "会社名")
        dept        = _get(row, "部署名")
        title       = _get(row, "役職")
        last        = _get(row, "姓")
        first       = _get(row, "名")
        email       = _get(row, "e-mail")
        postcode    = normalize_postcode(_get(row, "郵便番号"))
        addr_raw    = _get(row, "住所")
        tel_company = _get(row, "TEL会社")
        tel_dept    = _get(row, "TEL部門")
        tel_direct  = _get(row, "TEL直通")
        fax         = _get(row, "Fax")
        mobile      = _get(row, "携帯電話")
        url         = _get(row, "URL")

        # 住所分割（すでに v17 系ロジックを converters.address で採用済み）
        addr1, addr2 = split_address(addr_raw)

        # 電話を ";” 連結（会社／部門／直通／Fax／携帯）
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署 2分割（前半/後半）
        dept1, dept2 = split_department(dept)

        # 姓名
        full_name = f"{last}{first}"
        full_name_kana = ""  # 全体の読みは任意（必要なら utils.kana で組み立て）
        last_kana  = to_katakana_guess(last)
        first_kana = to_katakana_guess(first)

        # 会社名かな（会社種別を除外してから推定）
        company_for_kana = company
        for t in COMPANY_TYPES:
            company_for_kana = company_for_kana.replace(t, "")
        company_kana = to_katakana_guess(company_for_kana)

        # メモ/備考
        memo = ["", "", "", "", ""]
        biko = ""
        for hdr in custom_headers:
            val = _get(row, hdr)
            if val == "1":
                # メモ1..5 を順に埋める。それ以上は備考1へ改行追加
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        break
                else:
                    biko += (("\n" if biko else "") + hdr)

        # ==== ここが重要：ATENA_HEADERS と 1:1 で並べる（合計 61 列） ====
        out_row: List[str] = [
            # 1..9
            last, first, last_kana, first_kana, full_name, full_name_kana, "", "", "",
            # 10..12 + 13..17
            "", "", "", "", "", "", "", "",  # ニックネーム, 旧姓, 宛先, 自宅〒, 自宅住所1, 自宅住所2, 自宅住所3, 自宅電話
            # 18..21
            "", "", "", "",                  # 自宅IM ID, 自宅E-mail, 自宅URL, 自宅Social
            # 22..25
            postcode, addr1, addr2, "",      # 会社〒, 会社住所1, 会社住所2, 会社住所3
            # 26..28
            phone_join, "", email,           # 会社電話, 会社IM ID, 会社E-mail
            # 29..30
            url, "",                         # 会社URL, 会社Social
            # 31..39 （ここが 9 列！）
            "", "", "", "", "", "", "", "", "",  # その他〒, その他住所1, その他住所2, その他住所3, その他電話, その他IM ID, その他E-mail, その他URL, その他Social
            # 40..44
            company_kana, company, dept1, dept2, title,
            # 45..48
            "", "", "", "",                  # 連名, 連名ふりがな, 連名敬称, 連名誕生日
            # 49..53
            memo[0], memo[1], memo[2], memo[3], memo[4],
            # 54..56
            biko, "", "",                    # 備考1, 備考2, 備考3
            # 57..61
            "", "", "", "", ""               # 誕生日, 性別, 血液型, 趣味, 性格
        ]
        # 念のための安全装置（将来拡張での列ズレ防止）
        if len(out_row) < len(ATENA_HEADERS):
            out_row.extend([""] * (len(ATENA_HEADERS) - len(out_row)))
        elif len(out_row) > len(ATENA_HEADERS):
            out_row = out_row[:len(ATENA_HEADERS)]

        rows.append(out_row)

    # 書き出し
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows)
    return buf.getvalue()
