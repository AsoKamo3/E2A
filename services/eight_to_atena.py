# services/eight_to_atena.py
# Eight CSV → 宛名職人CSV への変換本体（I/Oなし・純粋関数）
# カラムのずれ／rows未定義の不具合を修正済み

import io
import csv

from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,
    to_katakana_guess,
    COMPANY_TYPES,
    ATENA_HEADERS,
    EIGHT_FIXED,
)
from converters.address import split_address

__version__ = "v1.6"

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    EightのエクスポートCSVテキストを受け取り、
    宛名職人の取り込み用CSVテキストを返す。
    """
    reader = csv.DictReader(io.StringIO(csv_text))

    # ★必ず初期化する（未定義エラー防止）
    rows = []

    for row in reader:
        g = lambda k: (row.get(k, "") or "").strip()

        company      = g("会社名")
        dept         = g("部署名")
        title        = g("役職")
        last         = g("姓")
        first        = g("名")
        email        = g("e-mail")
        postcode     = normalize_postcode(g("郵便番号"))
        addr_raw     = g("住所")
        tel_company  = g("TEL会社")
        tel_dept     = g("TEL部門")
        tel_direct   = g("TEL直通")
        fax          = g("Fax")
        mobile       = g("携帯電話")
        url          = g("URL")

        # 住所分割（内部で全角統一まで完了）
        addr1, addr2 = split_address(addr_raw)

        # 電話を連結
        phone_join   = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署を2分割
        dept1, dept2 = split_department(dept)

        # 姓名とかな
        full_name        = f"{last}{first}"
        full_name_kana   = ""
        last_kana        = to_katakana_guess(last)
        first_kana       = to_katakana_guess(first)

        # 会社名かな（会社種別語は除外して推定）
        company_for_kana = company
        for t in COMPANY_TYPES:
            company_for_kana = company_for_kana.replace(t, "")
        company_kana = to_katakana_guess(company_for_kana)

        # カスタム列 → メモ/備考（固定カラム以降で '1' のヘッダ名を格納）
        memo = ["", "", "", "", ""]
        biko = ""
        fixed_len = len(EIGHT_FIXED)
        for hdr in (reader.fieldnames or [])[fixed_len:]:
            val = (row.get(hdr, "") or "").strip()
            if val == "1":
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        break
                else:
                    biko += (("\n" if biko else "") + hdr)

        # 宛名職人1行分（ATENA_HEADERS順）
        out_row = [
            last, first,                   # 1-2: 姓, 名
            last_kana, first_kana,         # 3-4: 姓かな, 名かな
            full_name, full_name_kana,     # 5-6: 姓名, 姓名かな
            "", "", "",                    # 7-9: ミドルネーム, ミドルネームかな, 敬称
            "", "", "",                    # 10-12: ニックネーム, 旧姓, 宛先
            "", "", "", "", "",            # 13-17: 自宅〒, 自宅住所1-3, 自宅電話
            "", "", "", "",                # 18-21: 自宅IM, 自宅E-mail, 自宅URL, 自宅Social
            postcode, addr1, addr2, "",    # 22-25: 会社〒, 会社住所1-3
            phone_join, "", email,         # 26-28: 会社電話, 会社IM, 会社E-mail
            url, "",                       # 29-30: 会社URL, 会社Social
            "", "", "", "", "", "", "", "",# 31-39: その他〒, その他住所1-3, その他電話, その他IM, その他E-mail, その他URL, その他Social
            company_kana, company,         # 40-41: 会社名かな, 会社名
            dept1, dept2,                  # 42-43: 部署名1, 部署名2
            title,                         # 44: 役職名
            "", "", "", "",                # 45-48: 連名, 連名ふりがな, 連名敬称, 連名誕生日
            memo[0], memo[1], memo[2], memo[3], memo[4],  # 49-53: メモ1..5
            biko, "", "",                  # 54-56: 備考1..3
            "", "", "", ""                 # 57-60: 誕生日, 性別, 血液型, 趣味
        ]

        # 61列目: 性格（ATENA_HEADERSは計61要素）
        out_row.append("")  # 61

        # 念のため列数ガード（ズレ防止）
        if len(out_row) < len(ATENA_HEADERS):
            out_row += [""] * (len(ATENA_HEADERS) - len(out_row))
        elif len(out_row) > len(ATENA_HEADERS):
            out_row = out_row[:len(ATENA_HEADERS)]

        rows.append(out_row)

    # 出力CSV
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(ATENA_HEADERS)
    writer.writerows(rows)
    return buf.getvalue()
