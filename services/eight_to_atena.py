# services/eight_to_atena.py
# Eight CSV → 宛名職人CSV 変換本体（I/Oと行マッピングのみ）
# 住所分割は converters.address.split_address に委譲
# テキスト正規化は utils.textnorm を使用
# バージョン履歴:
#   v1.1: convert_eight_csv_text_to_atena_csv_text を本モジュールで唯一実装
#   v1.2: （一時）ヘッダ末尾の「性格」を削除した版
#   v1.3: ヘッダ末尾「性格」を復帰し、"その他" ブロックを厳密に9列出力（列ずれ修正）

__version__ = "v1.3"

import io
import csv

from utils.textnorm import (
    normalize_postcode,
    normalize_phone,
    split_department,
    to_katakana_guess,
)
from converters.address import split_address

# ====== 宛名職人ヘッダ（末尾は「性格」まで・順序厳守） ======
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
# 「その他〒～その他Social」は 9 列（インデックス 30..38）です。

# ====== Eight 側の固定カラム（この順で存在する想定） ======
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ====== 会社種別（かな除外対象） ======
COMPANY_TYPES = [
    "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    """
    Eight の CSV テキストを読み取り、宛名職人の CSV テキストへ変換して返す。
    - 出力は ATENA_HEADERS の順序に厳密に合わせる（カラムずれ防止）
    - 住所分割は converters.address.split_address を使用
    - ふりがな推定は utils.kana（utils.textnorm 経由の to_katakana_guess）を使用
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    out_rows = []

    for row in reader:
        g = lambda k: (row.get(k, "") or "").strip()

        # --- 入力（Eight） ---
        company     = g("会社名")
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

        # --- 電話まとめ（; 連結） ---
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # --- 部署の二分割 ---
        dept1, dept2 = split_department(dept)

        # --- 姓名とかな ---
        full_name       = f"{last}{first}"
        full_name_kana  = ""
        last_kana       = to_katakana_guess(last)
        first_kana      = to_katakana_guess(first)

        # --- 会社名かな（会社種別除去後に推定） ---
        company_for_kana = company
        for t in COMPANY_TYPES:
            company_for_kana = company_for_kana.replace(t, "")
        company_kana = to_katakana_guess(company_for_kana)

        # --- カスタム列: 値が "1" のヘッダ名をメモ1..5 / 溢れは備考1へ ---
        memo = ["", "", "", "", ""]
        biko = ""
        extra_headers = (reader.fieldnames or [])[len(EIGHT_FIXED):]
        for hdr in extra_headers:
            val = (row.get(hdr, "") or "").strip()
            if val == "1":
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        break
                else:
                    biko += (("\n" if biko else "") + hdr)

        # --- 宛名職人 行（ATENA_HEADERS と 1:1・列数チェック付き） ---
        out_row = [
            # 0-5: 姓/名/かな/姓名
            last, first,
            last_kana, first_kana,
            full_name, full_name_kana,

            # 6-11: ミドル～宛先
            "", "", "",         # ミドルネーム, ミドルネームかな, 敬称
            "", "", "",         # ニックネーム, 旧姓, 宛先

            # 12-20: 自宅系（未使用）
            "", "", "", "", "",            # 自宅〒, 自宅住所1..3, 自宅電話
            "", "", "", "",                # 自宅IM ID, 自宅E-mail, 自宅URL, 自宅Social

            # 21-29: 会社系
            postcode, addr1, addr2, "",    # 会社〒, 会社住所1, 会社住所2, 会社住所3
            phone_join, "", email,         # 会社電話, 会社IM ID, 会社E-mail
            url, "",                       # 会社URL, 会社Social

            # 30-38: その他系（**9列必須**）
            "", "", "", "", "", "", "", "",  # ← ここが9列（不足すると以降が1つ右へずれる）

            # 39-43: 会社名かな/会社名/部署/役職
            company_kana, company,         # 会社名かな, 会社名
            dept1, dept2,                  # 部署名1, 部署名2
            title,                         # 役職名

            # 44-47: 連名系（未使用）
            "", "", "", "",

            # 48-52: メモ1..5
            memo[0], memo[1], memo[2], memo[3], memo[4],

            # 53-55: 備考1..3
            biko, "", "",

            # 56-61: 誕生日/性別/血液型/趣味/性格（ヘッダ末尾まで）
            "", "", "", "", "",  # ← 「性格」まで
        ]

        # 安全チェック（ヘッダと列数が一致しない場合は例外）
        if len(out_row) != len(ATENA_HEADERS):
            raise RuntimeError(
                f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}"
            )

        out_rows.append(out_row)

    # --- 書き出し ---
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(out_rows)
    return buf.getvalue()
