# services/eight_to_atena.py
# Eight CSV -> 宛名職人 CSV 変換本体（I/O: テキスト→テキスト）
# 依存:
#   - converters.address.split_address
#   - utils.textnorm: to_zenkaku, normalize_postcode, normalize_phone, split_department
#   - utils.kana: to_katakana_guess

from __future__ import annotations

import csv
import io
from typing import List

from converters.address import split_address
from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,
)
from utils.kana import to_katakana_guess

__all__ = ["convert_eight_csv_text_to_atena_csv_text"]

# ====== 宛名職人ヘッダ ======
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

# ====== Eight 固定カラム（この順で存在する想定） ======
EIGHT_FIXED: List[str] = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ====== 会社種別（かな除外対象） ======
COMPANY_TYPES: List[str] = [
    "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]


def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    Eight の CSV テキストを読み取り、宛名職人の CSV テキストを返す。
    - 住所の分割は converters.address.split_address() を使用
    - 郵便/電話/部署分割などは utils.textnorm の関数を使用
    - ふりがな推定は utils.kana.to_katakana_guess() を使用（失敗可）
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_out: List[List[str]] = []

    # フィールド取得ヘルパ
    def g(row: dict, key: str) -> str:
        return (row.get(key, "") or "").strip()

    for row in reader:
        company = g(row, "会社名")
        dept = g(row, "部署名")
        title = g(row, "役職")
        last = g(row, "姓")
        first = g(row, "名")
        email = g(row, "e-mail")
        postcode = normalize_postcode(g(row, "郵便番号"))
        addr_raw = g(row, "住所")
        tel_company = g(row, "TEL会社")
        tel_dept = g(row, "TEL部門")
        tel_direct = g(row, "TEL直通")
        fax = g(row, "Fax")
        mobile = g(row, "携帯電話")
        url = g(row, "URL")

        # 住所分割（v17ロジックは converters/address 内）
        addr1, addr2 = split_address(addr_raw)

        # 会社電話（; 連結）
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署 2分割（全角スペース結合）
        dept1, dept2 = split_department(dept)

        # 氏名
        full_name = f"{last}{first}"
        full_name_kana = ""  #（任意）姓名かなは空欄のまま
        last_kana = to_katakana_guess(last)
        first_kana = to_katakana_guess(first)

        # 会社名かな（会社種別は除外してから推定）
        company_for_kana = company
        for t in COMPANY_TYPES:
            company_for_kana = company_for_kana.replace(t, "")
        company_kana = to_katakana_guess(company_for_kana)

        # カスタムフラグ列：固定以降のカラム名で値が "1" のものをメモへ
        memo = ["", "", "", "", ""]
        biko = ""
        extra_headers = (reader.fieldnames or [])[len(EIGHT_FIXED):]
        for hdr in extra_headers:
            val = g(row, hdr)
            if val == "1":
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        break
                else:
                    biko += (("\n" if biko else "") + hdr)

        out_row = [
            last, first,                   # 1-2: 姓, 名
            last_kana, first_kana,         # 3-4: 姓かな, 名かな
            full_name, full_name_kana,     # 5-6: 姓名, 姓名かな
            "", "", "",                    # 7-9: ミドル/ミドルかな/敬称
            "", "", "",                    # 10-12: ニック/旧姓/宛先
            "", "", "", "", "",            # 13-17: 自宅〒/住所1/住所2/住所3/電話
            "", "", "", "",                # 18-21: 自宅IM/E-mail/URL/Social
            postcode, addr1, addr2, "",    # 22-25: 会社〒/住所1/住所2/住所3
            phone_join, "", email,         # 26-28: 会社電話/IM/E-mail
            url, "",                       # 29-30: 会社URL/Social

            # ▼▼ その他（9個）: 〒 / 住所1 / 住所2 / 住所3 / 電話 / IM / E-mail / URL / Social
            "", "", "", "", "", "", "", "",  # 31-39

            company_kana, company,         # 40-41: 会社名かな, 会社名
            dept1, dept2,                  # 42-43: 部署名1, 部署名2
            title,                         # 44: 役職名
            "", "", "", "",                # 45-48: 連名系
            memo[0], memo[1], memo[2], memo[3], memo[4],   # 49-53: メモ1..5
            biko, "", "",                  # 54-56: 備考1..3
            "", "", "", ""                 # 57-61: 誕生日, 性別, 血液型, 趣味, 性格
        ]

        # ズレ防止の安全策（任意だが推奨）
        if len(out_row) < len(ATENA_HEADERS):
            out_row += [""] * (len(ATENA_HEADERS) - len(out_row))
        elif len(out_row) > len(ATENA_HEADERS):
            out_row = out_row[:len(ATENA_HEADERS)]

        rows.append(out_row)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return buf.getvalue()
