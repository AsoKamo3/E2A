# services/eight_to_atena.py
# Eight CSV → 宛名職人CSV 変換本体（I/Oと行マッピング）
# v2.29 : 会社種別語（法人格語）の一覧を外部 google2atena.corp_terms.CORP_TERMS が
#         存在すれば優先採用。無ければ内蔵デフォルトを使用。
#         ふりがなは utils.kana 側の拡張（外部辞書マージ）をそのまま利用。

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

__version__ = "v2.29"

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

# 会社種別（外部があれば優先採用）
try:
    from google2atena.corp_terms import CORP_TERMS as _EXT_CORP_TERMS  # type: ignore
    COMPANY_TYPES = list(_EXT_CORP_TERMS)
except Exception:
    COMPANY_TYPES = [
        "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
        "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
        "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
        "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
        "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
        "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託","公共団体",
        "協会","研究所","機構","振興会","財団","基金","商工会議所","商工会"
    ]

def _strip_company_type(name: str) -> str:
    base = name or ""
    # 長語優先で除去
    for t in sorted(COMPANY_TYPES, key=len, reverse=True):
        base = base.replace(t, "")
    return base

def _company_kana_guess(company_name: str) -> str:
    base = _strip_company_type(company_name or "")
    kana = company_kana_from_name(base)
    return ensure_katakana(kana)

def _iter_extra_flags(fieldnames: List[str], row: dict) -> List[str]:
    flags = []
    tail_headers = fieldnames[len(EIGHT_FIXED):] if fieldnames else []
    for hdr in tail_headers:
        val = (row.get(hdr, "") or "").strip()
        if val == "1":
            flags.append(hdr)
    return flags

def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_out: List[List[str]] = []

    for row in reader:
        g = lambda k: (row.get(k, "") or "").strip()

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

        addr1, addr2 = split_address(addr_raw)
        phone_join   = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)
        dept1, dept2 = split_department(dept)

        full_name        = f"{last}{first}"
        last_kana        = ensure_katakana(to_katakana_guess(last))
        first_kana       = ensure_katakana(to_katakana_guess(first))
        full_name_kana   = ensure_katakana(f"{last_kana}{first_kana}") if (last_kana or first_kana) else ""
        company_kana     = _company_kana_guess(company)

        if not company.strip():
            company = company_raw.strip()

        flags = _iter_extra_flags(reader.fieldnames or [], row)
        memo = ["", "", "", "", ""]
        biko = ""
        for i, hdr in enumerate(flags):
            if i < 5:
                memo[i] = hdr
            else:
                biko += (("\n" if biko else "") + hdr)

        out_row: List[str] = [
            last, first,
            last_kana, first_kana,
            full_name, full_name_kana,
            "", "", "",
            "", "", "",

            "", "", "", "", "",
            "", "", "", "",

            postcode, addr1, addr2, "",
            phone_join, "", email,
            url, "",

            "", "", "", "", "", "", "", "",

            company_kana, company,
            to_zenkaku(dept1), to_zenkaku(dept2),
            to_zenkaku(title),
            "", "", "", "",

            memo[0], memo[1], memo[2], memo[3], memo[4],
            biko, "", "",

            "", "", "", "", ""
        ]

        if len(out_row) != len(ATENA_HEADERS):
            raise ValueError(f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}")

        rows_out.append(out_row)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return buf.getvalue()
