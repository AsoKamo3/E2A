# -*- coding: utf-8 -*-
"""
Eight → 宛名職人 変換コア
- v2.32: 宛名職人CSVの固定ヘッダを常に出力するように修正（Eightヘッダをパススルーしない）
         入力ゆらぎに強い列取得（存在しない列は空文字）/ 郵便番号・電話の軽整形

注意:
- ここでは「出力フォーマットの厳守」を最優先。
- Kana 付与の高度化や会社名カナのオーバーライドは別モジュール（utils.kana / textnorm）側のまま。
- まずは Eight列 → 宛名職人列 への最低限のマッピングで“必ず宛名職人列ヘッダを出力”します。

依存:
- utils.textnorm: normalize_postcode, normalize_phone
"""

from __future__ import annotations

__version__ = "v2.32"

import csv
import io
from typing import Dict, List, Optional

from utils.textnorm import normalize_postcode, normalize_phone

# 宛名職人の出力ヘッダ（以前あなたが提示した並びを採用）
ATENA_HEADERS: List[str] = [
    "姓", "名", "姓かな", "名かな",
    "姓名", "姓名かな",
    "ミドルネーム", "ミドルネームかな",
    "敬称", "ニックネーム", "旧姓", "宛先",
    "自宅〒", "自宅住所1", "自宅住所2", "自宅住所3",
    "自宅電話", "自宅IM ID", "自宅E-mail", "自宅URL", "自宅Social",
    "会社〒", "会社住所1", "会社住所2", "会社住所3",
    "会社電話", "会社IM ID", "会社E-mail",
]

# Eight 側で“ありそう”な列名の候補（存在チェックして拾う）
# ※ 入力のゆらぎに合わせて随時ここを増やせます（英語エクスポート等）
CANDIDATE = {
    "sei": ["姓", "名字", "氏", "姓（漢字）", "Last Name", "Family Name"],
    "mei": ["名", "名前", "名（漢字）", "First Name", "Given Name"],
    "sei_kana": ["姓カナ", "せいカナ", "姓かな", "セイ"],
    "mei_kana": ["名カナ", "めいカナ", "名かな", "メイ"],
    "nickname": ["ニックネーム", "呼称", "呼び名", "Nickname"],
    "honorific": ["敬称"],
    "old_surname": ["旧姓"],
    "addr_zip_home": ["自宅郵便番号", "郵便番号", "自宅〒", "Zip", "ZIP", "Postcode"],
    "addr_home": ["自宅住所", "住所", "住所1", "Address", "Address1"],
    "addr_home2": ["自宅住所2", "住所2", "Address2"],
    "addr_home3": ["自宅住所3", "住所3", "Address3"],
    "tel_home": ["自宅電話", "電話（自宅）", "TEL（自宅）", "Phone(Home)"],
    "email_home": ["自宅E-mail", "メール（自宅）", "E-mail(Home)", "メールアドレス"],
    "url_home": ["自宅URL", "URL", "ホームページ"],
    "social_home": ["自宅Social", "SNS", "Twitter", "X", "Facebook", "Instagram"],

    "company": ["会社名", "勤務先", "会社", "Organization", "Company"],
    "addr_zip_company": ["会社郵便番号", "会社〒", "勤務先郵便番号"],
    "addr_company": ["会社住所", "会社住所1", "勤務先住所", "会社所在地", "Office Address"],
    "addr_company2": ["会社住所2", "勤務先住所2", "Office Address2"],
    "addr_company3": ["会社住所3", "勤務先住所3", "Office Address3"],
    "tel_company": ["会社電話", "電話（会社）", "TEL（会社）", "Phone(Work)"],
    "email_company": ["会社E-mail", "メール（会社）", "E-mail(Work)"],
    "im_home": ["自宅IM ID", "IM(Home)"],
    "im_company": ["会社IM ID", "IM(Work)"],
    "title": ["役職", "肩書", "Title"],
    "dept": ["部署", "Department"],
}


def _pick(row: Dict[str, str], keys: List[str]) -> str:
    """候補キー列から最初に見つかった値を返す（無ければ空）"""
    for k in keys:
        if k in row and row[k] is not None:
            v = str(row[k]).strip()
            if v != "":
                return v
    return ""


def _full_name(sei: str, mei: str) -> str:
    s = (sei or "").strip()
    m = (mei or "").strip()
    if not s and not m:
        return ""
    # 日本式：姓 名
    return f"{s}{(' ' if s and m else '')}{m}"


def _full_name_kana(sei_k: str, mei_k: str) -> str:
    s = (sei_k or "").strip()
    m = (mei_k or "").strip()
    if not s and not m:
        return ""
    return f"{s}{(' ' if s and m else '')}{m}"


def _normalize_postcode(s: str) -> str:
    return normalize_postcode(s) or ""


def _normalize_phone(s: str) -> str:
    return normalize_phone(s) or ""


def _detect_delimiter(sample: str) -> str:
    # タブ優先。TSV/Eightの混在に強め
    if "\t" in sample and sample.count("\t") >= sample.count(","):
        return "\t"
    return ","


def convert_eight_csv_text_to_atena_csv_text(src_text: str) -> str:
    """
    入力: Eightエクスポート（CSV/TSV, UTF-8想定）
    出力: 宛名職人CSV（UTF-8, カンマ区切り, 固定ヘッダ ATENA_HEADERS）
    """
    if not isinstance(src_text, str):
        raise ValueError("src_text is not str")

    # 1) 入力読み込み（区切りをざっくり判定）
    delim = _detect_delimiter(src_text.splitlines()[0] if src_text.splitlines() else ",")
    src = io.StringIO(src_text)
    reader = csv.DictReader(src, delimiter=delim)

    # 2) 出力：必ず “宛名職人ヘッダ” を書く
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=ATENA_HEADERS, extrasaction="ignore")
    writer.writeheader()

    # 3) 行ごとに最低限のマッピング
    for row in reader:
        # --- 基本項目 ---
        sei = _pick(row, CANDIDATE["sei"])
        mei = _pick(row, CANDIDATE["mei"])
        sei_kana = _pick(row, CANDIDATE["sei_kana"])
        mei_kana = _pick(row, CANDIDATE["mei_kana"])
        nickname = _pick(row, CANDIDATE["nickname"])
        honor = _pick(row, CANDIDATE["honorific"])
        old_sei = _pick(row, CANDIDATE["old_surname"])

        # --- 自宅系 ---
        zip_home = _normalize_postcode(_pick(row, CANDIDATE["addr_zip_home"]))
        addr1_home = _pick(row, CANDIDATE["addr_home"])
        addr2_home = _pick(row, CANDIDATE["addr_home2"])
        addr3_home = _pick(row, CANDIDATE["addr_home3"])
        tel_home = _normalize_phone(_pick(row, CANDIDATE["tel_home"]))
        im_home = _pick(row, CANDIDATE["im_home"])
        email_home = _pick(row, CANDIDATE["email_home"])
        url_home = _pick(row, CANDIDATE["url_home"])
        social_home = _pick(row, CANDIDATE["social_home"])

        # --- 会社系 ---
        zip_company = _normalize_postcode(_pick(row, CANDIDATE["addr_zip_company"]))
        addr1_company = _pick(row, CANDIDATE["addr_company"])
        addr2_company = _pick(row, CANDIDATE["addr_company2"])
        addr3_company = _pick(row, CANDIDATE["addr_company3"])
        tel_company = _normalize_phone(_pick(row, CANDIDATE["tel_company"]))
        im_company = _pick(row, CANDIDATE["im_company"])
        email_company = _pick(row, CANDIDATE["email_company"])

        # 宛先は、会社名+部署+役職+姓名 などの運用も考えられるが、まずは空/既存フィールドで安全運用
        # ここでは Eight側に「宛先」列があれば拾い、なければ空。
        addressee = row.get("宛先", "") or ""

        rec = {
            "姓": sei,
            "名": mei,
            "姓かな": sei_kana,
            "名かな": mei_kana,
            "姓名": _full_name(sei, mei),
            "姓名かな": _full_name_kana(sei_kana, mei_kana),
            "ミドルネーム": "",
            "ミドルネームかな": "",
            "敬称": honor,
            "ニックネーム": nickname,
            "旧姓": old_sei,
            "宛先": addressee,

            "自宅〒": zip_home,
            "自宅住所1": addr1_home,
            "自宅住所2": addr2_home,
            "自宅住所3": addr3_home,
            "自宅電話": tel_home,
            "自宅IM ID": im_home,
            "自宅E-mail": email_home,
            "自宅URL": url_home,
            "自宅Social": social_home,

            "会社〒": zip_company,
            "会社住所1": addr1_company,
            "会社住所2": addr2_company,
            "会社住所3": addr3_company,
            "会社電話": tel_company,
            "会社IM ID": im_company,
            "会社E-mail": email_company,
        }
        writer.writerow(rec)

    return out.getvalue()
