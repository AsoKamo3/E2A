# services/eight_to_atena.py
# Eight CSV → 宛名職人CSV 変換本体

import csv
import io

from converters.address import split_address
from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,          # ← ここが今回のポイント（必ずこの関数を使う）
)
from utils.kana import to_katakana_guess

__version__ = "v2.7"  # ← バージョンをひとつ上げました（部署分割の安定化）

# 宛名職人のヘッダ
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

# Eight 側の固定カラム（この順で来る想定）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# 会社種別（かな生成時の除去対象）
COMPANY_TYPES = [
    "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]

def _company_kana_guess(company: str) -> str:
    s = company or ""
    for t in COMPANY_TYPES:
        s = s.replace(t, "")
    return to_katakana_guess(s)

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    EightエクスポートCSV(UTF-8, カンマ区切り) → 宛名職人CSV(UTF-8)
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_out = []

    for row in reader:
        g = lambda k: (row.get(k, "") or "").strip()

        company = g("会社名")
        dept = g("部署名")
        title = g("役職")
        last = g("姓")
        first = g("名")
        email = g("e-mail")
        postcode = normalize_postcode(g("郵便番号"))
        addr_raw = g("住所")
        tel_company = g("TEL会社")
        tel_dept = g("TEL部門")
        tel_direct = g("TEL直通")
        fax = g("Fax")
        mobile = g("携帯電話")
        url = g("URL")

        # 住所分割
        addr1, addr2 = split_address(addr_raw)

        # 電話連結（; で結ぶ）
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署 2 分割（← 今回の修正点が効く）
        dept1, dept2 = split_department(dept)

        # 姓名
        full_name = f"{last}{first}"
        full_name_kana = ""  # かな自動は任意（kana.py で切替可能）
        last_kana = to_katakana_guess(last)
        first_kana = to_katakana_guess(first)

        company_kana = _company_kana_guess(company)

        # メモ系（固定カラム以降に '1' が立っているヘッダ名を順に格納）
        memo = ["", "", "", "", ""]
        biko = ""
        for hdr in (reader.fieldnames or [])[len(EIGHT_FIXED):]:
            val = (row.get(hdr, "") or "").strip()
            if val == "1":
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        break
                else:
                    biko += (("\n" if biko else "") + hdr)

        # 宛名職人の列順に合わせて厳密に並べる（※順番厳守）
        out_row = [
            last, first,                   # 姓, 名
            last_kana, first_kana,         # 姓かな, 名かな
            full_name, full_name_kana,     # 姓名, 姓名かな
            "", "", "",                    # ミドル/敬称
            "", "", "",                    # ニック/旧姓/宛先
            "", "", "", "", "",            # 自宅系 未使用
            "", "", "", "",                # 自宅続き
            postcode, addr1, addr2, "",    # 会社〒, 会社住所1, 会社住所2, 会社住所3
            phone_join, "", email,         # 会社電話, 会社IM, 会社E-mail
            url, "",                       # 会社URL, 会社Social
            "", "", "", "", "", "", "", "",# その他*
            company_kana, company,         # 会社名かな, 会社名
            dept1, dept2,                  # 部署名1, 部署名2（←ここが重要）
            title,                         # 役職名
            "", "", "", "",                # 連名*
            memo[0], memo[1], memo[2], memo[3], memo[4],   # メモ1..5
            biko, "", "",                  # 備考1..3
            "", "", "", ""                 # 誕生日, 性別, 血液型, 趣味, 性格
        ]
        rows_out.append(out_row)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return buf.getvalue()
