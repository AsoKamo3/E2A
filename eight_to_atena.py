# -*- coding: utf-8 -*-
"""
eight_to_atena.py  v1.1.1  (hotfix: SyntaxError 修正)

Eight の書き出しCSVを「宛名職人」CSVに変換するワンファイルツール。
- 文字コード: UTF-8
- 区切り: カンマ
- 住所1/住所2 は全角統一
- 郵便番号は xxx-xxxx に整形（半角）
- 会社電話は複数候補を ; で結合（スペースなし）
- 部署名はルールに基づき部署名1/部署名2へ分割（全角、＋の前後は全角スペース）
- カスタム列(固定列以降)は「1」の列ヘッダを上から順に メモ1..5、その超過分は 備考1（改行区切り）へ
- “ふりがな”は簡易推定（カタカナ化）*漢字のみ等で推定困難な場合は空欄のまま可
- 会社名かなは法人種別語（株式会社等）は除外して付与
"""

import csv
import re
import sys
import argparse
from pathlib import Path

VERSION = "v1.1.1"

# ---- Eight 側の固定ヘッダ（ここまでが固定列） ----
EIGHT_FIXED_HEADER = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ---- 宛名職人の出力ヘッダ ----
ATENA_HEADER = [
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

# ---- 法人種別（会社名かな から除外）----
CORP_WORDS = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "相互会社", "清算株式会社",
    "一般社団法人", "一般財団法人", "公益社団法人", "公益財団法人",
    "特定非営利活動法人", "ＮＰＯ法人", "中間法人", "有限責任中間法人", "特例民法法人",
    "学校法人", "医療法人", "医療法人社団", "医療法人財団", "宗教法人", "社会福祉法人",
    "国立大学法人", "公立大学法人", "独立行政法人", "地方独立行政法人",
    "特殊法人",
    "有限責任事業組合", "投資事業有限責任組合", "特定目的会社", "特定目的信託"
]

# ---- 全角変換（英数字・記号） ----
ZEN_MAP = str.maketrans(
    {
        **{str(i): chr(ord("０") + i) for i in range(10)},
        **{chr(ord("a")+i): chr(ord("ａ")+i) for i in range(26)},
        **{chr(ord("A")+i): chr(ord("Ａ")+i) for i in range(26)},
        "-": "－", "_": "＿", " ": "　", "/": "／", "#": "＃",
        ".": "．", ",": "，", ":": "：", ";": "；", "&": "＆",
        "(": "（", ")": "）", "[": "［", "]": "］", "'": "’",
        "\"": "”", "+": "＋", "!": "！", "?": "？", "@": "＠",
        "*": "＊"
    }
)

def to_zenkaku(s: str) -> str:
    if not s:
        return s
    return s.translate(ZEN_MAP)

def to_katakana_simple(s: str) -> str:
    if not s:
        return s
    s = re.sub(r'[ぁ-ゖ]', lambda m: chr(ord(m.group(0)) + 0x60), s)
    s = s.encode("utf-8", "ignore").decode("utf-8")
    return s

def strip_corp_words(name: str) -> str:
    s = name or ""
    for w in CORP_WORDS:
        s = s.replace(w, "")
    return s.strip()

def normalize_postal(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return raw

def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"[^\d+]", "", raw)
    m = re.match(r"^(070|080|090)(\d{4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(0[346])(\d{4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(0\d{2})(\d{3,4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw

def join_phones(parts):
    nums = [normalize_phone(p) for p in parts if p and str(p).strip()]
    nums = [n for n in nums if n]
    return ";".join(nums)

def normalize_dept_text(s: str) -> str:
    if not s:
        return ""
    s = to_zenkaku(s)
    s = re.sub(r"[ \u3000]+", "　", s.strip())
    return s

def split_department(dept: str) -> tuple[str, str]:
    if not dept or not str(dept).strip():
        return ("","")
    s = normalize_dept_text(dept)
    parts = re.split(r"[＞>／/｜|＞＞]+|　{2,}| +", s)
    parts = [p for p in parts if p]
    if not parts:
        return ("","")
    n = len(parts)
    if n == 1:
        return (parts[0], "")
    if n == 2:
        return (parts[0], parts[1])
    if n == 3:
        return (f"{parts[0]}　＋　{parts[1]}", parts[2])
    if n == 4:
        return (f"{parts[0]}　＋　{parts[1]}", f"{parts[2]}　＋　{parts[3]}")
    if n == 5:
        return (f"{parts[0]}　＋　{parts[1]}　＋　{parts[2]}", f"{parts[3]}　＋　{parts[4]}")
    return (f"{parts[0]}　＋　{parts[1]}　＋　{parts[2]}", f"{parts[3]}　＋　{parts[4]}　＋　{parts[5]}")

BUILDING_TOKENS = (
    r"ビル|タワー|タワーズ|シティ|ヒルズ|スクエア|ガーデン|プレイス|"
    r"コート|テラス|センター|プラザ|レジデンス|マンション|ハイツ|"
    r"コーポ|メゾン|パーク|パレス|キャッスル|ステーション|モール|"
    r"パルコ|オフィス|ウォール|カレッジ|ドーム|ハウス|スタジアム"
)

def split_address(addr: str) -> tuple[str, str]:
    if addr is None:
        return ("", "")
    a = addr.strip()

    if re.fullmatch(r"[A-Za-z0-9\s,.\-/#()]+", a):
        return ("", a)

    H = r"[\-－–—ーｰ]"

    def _last_address_block(s: str):
        pat_blocks = [
            r"\d+丁目\d+番\d+号",
            rf"\d+{H}\d+{H}\d+{H}\d+",
            rf"\d+{H}\d+{H}\d+",
            rf"\d+{H}\d+",
            r"\d+",
        ]
        for pat in pat_blocks:
            m = list(re.finditer(pat, s))
            if m:
                return m[-1]
        return None

    m = re.search(rf"^(.*?)(\d+{H}\d+{H}\d+){H}(\d+)(.*)$", a)
    if m:
        head = (m.group(1) or "") + (m.group(2) or "")
        tail = (m.group(3) or "") + (m.group(4) or "")
        return (head, tail)

    m = re.search(rf"^(.*?\d+丁目\d+番\d+号)(.+)$", a)
    if m:
        return (m.group(1), m.group(2))

    mlast = _last_address_block(a)
    if mlast and mlast.end() < len(a):
        tail = a[mlast.end():]
        if re.match(r"^[^\d０-９]", tail):
            if re.search(BUILDING_TOKENS, tail, flags=re.IGNORECASE):
                return (a[:mlast.end()], tail)

    for tok in ["階", "F", "Ｆ", "室", "号室", "内"]:
        t = re.search(re.escape(tok), a)
        if t:
            mb = _last_address_block(a[:t.start()])
            if mb:
                return (a[:mb.end()], a[mb.end():])
            else:
                return (a[:t.start()], a[t.start():])

    return (a, "")

def finalize_address(addr_raw: str) -> tuple[str, str]:
    if not addr_raw or not str(addr_raw).strip():
        return ("","")
    a1, a2 = split_address(str(addr_raw))
    a1 = to_zenkaku(a1)
    a2 = to_zenkaku(a2)
    SPECIAL = ["ＮＨＫ内","大学構内","センター内","工場内","構内","院内","校内"]
    for sp in SPECIAL:
        if sp in a1:
            a1 = a1.replace(sp, "")
            a2 = (a2 + sp).strip()
    a1 = re.sub(r"　+", "　", a1).strip()
    a2 = re.sub(r"　+", "　", a2).strip()
    return (a1, a2)

def guess_kana(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    s_k = to_katakana_simple(s)
    has_kana = re.search(r"[ァ-ヴーｦ-ﾟぁ-ゖ]", s_k) is not None
    return s_k if has_kana else ""

def guess_company_kana(company: str) -> str:
    base = strip_corp_words(company or "")
    return guess_kana(base)

def convert_row(eight_row: dict, custom_headers: list[str]) -> list[str]:
    last = (eight_row.get("姓") or "").strip()
    first = (eight_row.get("名") or "").strip()
    email = (eight_row.get("e-mail") or "").strip()
    postal = normalize_postal(eight_row.get("郵便番号") or "")
    addr_raw = eight_row.get("住所") or ""
    tel_company = eight_row.get("TEL会社") or ""
    tel_dept = eight_row.get("TEL部門") or ""
    tel_direct = eight_row.get("TEL直通") or ""
    fax = eight_row.get("Fax") or ""
    mobile = eight_row.get("携帯電話") or ""
    url = eight_row.get("URL") or ""
    company = eight_row.get("会社名") or ""
    dept = eight_row.get("部署名") or ""
    title = eight_row.get("役職") or ""

    addr1, addr2 = finalize_address(addr_raw)
    company_tel = join_phones([tel_company, tel_dept, tel_direct, fax, mobile])
    dept1, dept2 = split_department(dept)

    sei_kana = guess_kana(last)
    mei_kana = guess_kana(first)
    seimei = f"{last}{first}"
    seimei_kana = f"{sei_kana}{mei_kana}" if (sei_kana or mei_kana) else ""
    company_kana = guess_company_kana(company)

    memo_list = []
    biko_list = []
    for h in custom_headers:
        val = eight_row.get(h, "")
        if str(val).strip() == "1":
            memo_list.append(h)
    if len(memo_list) > 5:
        biko_list = memo_list[5:]
        memo_list = memo_list[:5]

    memo1 = memo_list[0] if len(memo_list) > 0 else ""
    memo2 = memo_list[1] if len(memo_list) > 1 else ""
    memo3 = memo_list[2] if len(memo_list) > 2 else ""
    memo4 = memo_list[3] if len(memo_list) > 3 else ""
    memo5 = memo_list[4] if len(memo_list) > 4 else ""
    biko1 = "\n".join(biko_list) if biko_list else ""
    biko2 = ""
    biko3 = ""

    out = [
        last, first,
        sei_kana, mei_kana,
        seimei, seimei_kana,
        "", "", "",
        "", "",
        "",
        "", "", "", "",
        "",
        "", "", "", "",
        postal,
        addr1, addr2, "",
        company_tel,
        "",
        email,
        url,
        "",
        "", "", "", "", "", "", "", "",
        company_kana,
        company,
        dept1, dept2,
        to_zenkaku(title) if title else "",
        "", "", "",
        memo1, memo2, memo3, memo4, memo5,
        biko1, biko2, biko3,
        "", "", "", "", ""
    ]
    return out  # ← ここが欠けていると配列未閉鎖っぽく見えることがあります

def convert_eight_csv_to_atena_csv(input_csv_path: str, output_csv_path: str) -> None:
    in_path = Path(input_csv_path)
    out_path = Path(output_csv_path)

    with in_path.open("r", encoding="utf-8", newline="") as f_in, \
         out_path.open("w", encoding="utf-8", newline="") as f_out:

        reader = csv.DictReader(f_in)
        all_headers = reader.fieldnames or []
        if not all_headers:
            raise ValueError("入力CSVのヘッダが読み取れません。")

        custom_headers = [h for h in all_headers if h not in EIGHT_FIXED_HEADER]

        writer = csv.writer(f_out)
        writer.writerow(ATENA_HEADER)

        for row in reader:
            out_row = convert_row(row, custom_headers)
            writer.writerow(out_row)

def main():
    ap = argparse.ArgumentParser(description=f"Eight CSV → 宛名職人 CSV 変換ツール ({VERSION})")
    ap.add_argument("-i", "--input", required=True, help="Eight 書き出しCSV (UTF-8)")
    ap.add_argument("-o", "--output", required=True, help="宛名職人用 出力CSV (UTF-8)")
    args = ap.parse_args()

    print(f"[eight_to_atena] version {VERSION}")
    convert_eight_csv_to_atena_csv(args.input, args.output)
    print(f"Done. → {args.output}")

if __name__ == "__main__":
    main()
