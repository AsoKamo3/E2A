# services/eight_to_atena.py
# Eight CSV → 宛名職人CSV 変換本体（I/Oと行マッピング）
from __future__ import annotations
import io
import csv

from converters.address import split_address
from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,
)
from utils.kana import to_katakana_guess  # ← 正しい所在

__version__ = "1.8"

# 宛名職人のヘッダ（61列）— この順序に厳密に合わせて出力する
ATENA_HEADERS = [
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

# Eight 固定カラム（先頭の既知列）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

def _get(row, key):
    return (row.get(key, "") or "").strip()

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    reader = csv.DictReader(io.StringIO(csv_text))
    out_rows = []

    # 可変列（固定以降）で「値が '1' の列名」をメモへ
    variable_headers = (reader.fieldnames or [])[len(EIGHT_FIXED):]

    for row in reader:
        company = _get(row, "会社名")
        dept = _get(row, "部署名")
        title = _get(row, "役職")
        last = _get(row, "姓")
        first = _get(row, "名")
        email = _get(row, "e-mail")
        postcode = normalize_postcode(_get(row, "郵便番号"))
        addr_raw = _get(row, "住所")
        tel_company = _get(row, "TEL会社")
        tel_dept = _get(row, "TEL部門")
        tel_direct = _get(row, "TEL直通")
        fax = _get(row, "Fax")
        mobile = _get(row, "携帯電話")
        url = _get(row, "URL")

        # 住所分割（住所1/住所2 最終的に to_zenkaku 済）
        addr1, addr2 = split_address(addr_raw)

        # 電話：; 連結（会社/部門/直通/FAX/携帯）
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署を2分割
        dept1, dept2 = split_department(dept)

        # 姓名・かな
        full_name = f"{last}{first}"
        last_kana = to_katakana_guess(last)
        first_kana = to_katakana_guess(first)
        full_name_kana = ""  # ここは空欄運用（必要なら結合）

        # 会社名かな（株式会社などは事前除去は行わず、そのまま推定）
        company_kana = to_katakana_guess(company)

        # メモ系（可変列で値が "1" の列名を順に詰める／超過分は備考1へ）
        memo = ["", "", "", "", ""]
        biko1 = ""
        for hdr in variable_headers:
            if (_get(row, hdr) == "1"):
                # 空いているメモ枠へ
                placed = False
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        placed = True
                        break
                if not placed:
                    biko1 += (("\n" if biko1 else "") + hdr)

        # ====== ここから出力配列（61列）を“ヘッダ順”で厳密に構築 ======
        out_row = [
            # 1-12: 氏名系
            last,                        # 1 姓
            first,                       # 2 名
            last_kana,                   # 3 姓かな
            first_kana,                  # 4 名かな
            full_name,                   # 5 姓名
            full_name_kana,              # 6 姓名かな
            "",                          # 7 ミドルネーム
            "",                          # 8 ミドルネームかな
            "",                          # 9 敬称
            "",                          # 10 ニックネーム
            "",                          # 11 旧姓
            "",                          # 12 宛先

            # 13-21: 自宅系（未使用）
            "", "", "", "", "", "", "", "",

            # 22-30: 会社系（郵便/住所/電話/URLなど）
            postcode,                    # 22 会社〒
            addr1,                       # 23 会社住所1
            addr2,                       # 24 会社住所2
            "",                          # 25 会社住所3
            phone_join,                  # 26 会社電話
            "",                          # 27 会社IM ID
            email,                       # 28 会社E-mail
            url,                         # 29 会社URL
            "",                          # 30 会社Social

            # 31-39: その他系（未使用）
            "", "", "", "", "", "", "", "",

            # 40-44: 会社名かな/会社名/部署/役職
            company_kana,                # 40 会社名かな
            company,                     # 41 会社名
            to_zenkaku(dept1),           # 42 部署名1
            to_zenkaku(dept2),           # 43 部署名2
            to_zenkaku(title),           # 44 役職名

            # 45-48: 連名系（未使用）
            "", "", "", "",

            # 49-53: メモ1..5
            memo[0], memo[1], memo[2], memo[3], memo[4],

            # 54-56: 備考1..3
            biko1, "", "",

            # 57-61: 誕生日/性別/血液型/趣味/性格
            "", "", "", "",  # 57-60
            "",              # 61
        ]

        # 最終安全チェック：列数がヘッダと一致しない場合はエラー
        if len(out_row) != len(ATENA_HEADERS):
            raise ValueError(f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}")

        out_rows.append(out_row)

    # CSV化
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(out_rows)
    return buf.getvalue()
