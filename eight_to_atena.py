# -*- coding: utf-8 -*-
"""
eight_to_atena.py  v1.0

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

出力ヘッダ（宛名職人）:
["姓","名","姓かな","名かな","姓名","姓名かな","ミドルネーム","ミドルネームかな","敬称",
 "ニックネーム","旧姓","宛先","自宅〒","自宅住所1","自宅住所2","自宅住所3","自宅電話",
 "自宅IM ID","自宅E-mail","自宅URL","自宅Social",
 "会社〒","会社住所1","会社住所2","会社住所3","会社電話","会社IM ID","会社E-mail",
 "会社URL","会社Social",
 "その他〒","その他住所1","その他住所2","その他住所3","その他電話","その他IM ID",
 "その他E-mail","その他URL","その他Social",
 "会社名かな","会社名","部署名1","部署名2","役職名",
 "連名","連名ふりがな","連名敬称","連名誕生日",
 "メモ1","メモ2","メモ3","メモ4","メモ5",
 "備考1","備考2","備考3","誕生日","性別","血液型","趣味","性格"]
"""

import csv
import re
import sys
import argparse
from pathlib import Path

VERSION = "v1.0"
print(f"[eight_to_atena] version {VERSION}")

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
        # 数字
        **{str(i): chr(ord("０") + i) for i in range(10)},
        # 英小文字
        **{chr(ord("a")+i): chr(ord("ａ")+i) for i in range(26)},
        # 英大文字
        **{chr(ord("A")+i): chr(ord("Ａ")+i) for i in range(26)},
        # 記号の主なもの
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

# ---- ひらがな→カタカナ / 半角ｶﾅ→全角カナ ----
def to_katakana_simple(s: str) -> str:
    if not s:
        return s
    # ひらがな→カタカナ
    s = re.sub(r'[ぁ-ゖ]', lambda m: chr(ord(m.group(0)) + 0x60), s)
    # 半角ｶﾅ→全角（ざっくり）
    s = s.encode("utf-8", "ignore").decode("utf-8")
    # ローマ字等は全角にしてそのまま（推測不能な漢字は空欄可）
    return s

def strip_corp_words(name: str) -> str:
    s = name or ""
    for w in CORP_WORDS:
        s = s.replace(w, "")
    return s.strip()

# ---- 郵便番号整形 xxx-xxxx（半角・ハイフンあり） ----
def normalize_postal(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return raw  # そのまま返す（異常系）

# ---- 電話番号整形 ----
# ルール：
# - 携帯: 0x0-xxxx-xxxx
# - 市外局番 03/04/06: 0x-xxxx-xxxx
# - その他: NTT標準（ここでは 0A-BCDE-FGHI の近似ルール）
# - ハイフンは必ず入れて半角、複数は ; で連結（スペースなし）
def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"[^\d+]", "", raw)  # 数字と + 以外除去
    # 国番号先頭は今回は国内前提で単純化
    # 携帯: 070/080/090
    m = re.match(r"^(070|080|090)(\d{4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # 03/04/06
    m = re.match(r"^(0[346])(\d{4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # それ以外（ざっくり）: 0AA-BBBB-CCCC or 0AAA-BBB-CCCC
    m = re.match(r"^(0\d{2})(\d{3,4})(\d{4})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw  # 整形不能は素通し

def join_phones(parts):
    nums = [normalize_phone(p) for p in parts if p and str(p).strip()]
    nums = [n for n in nums if n]
    return ";".join(nums)

# ---- 部署名分割（全角＋ 全角スペースで連結）----
def normalize_dept_text(s: str) -> str:
    if not s:
        return ""
    s = to_zenkaku(s)
    # 半角/全角スペースを全角スペースに
    s = re.sub(r"[ \u3000]+", "　", s.strip())
    return s

def split_department(dept: str) -> tuple[str, str]:
    """
    入力を「>」「/」「｜」「|」「＞」などの区切りやスペース分割で階層化
    ルール：
      2階層: 前=1, 後=2
      3階層: 前=1+2, 後=3
      4階層: 前=1+2, 後=3+4
      5階層: 前=1+2+3, 後=4+5
      6階層: 前=1+2+3, 後=4+5+6
    連結の「+」は全角、前後に全角スペース
    文字は全角統一
    """
    if not dept or not str(dept).strip():
        return ("","")
    s = normalize_dept_text(dept)
    # 区切りで分割
    parts = re.split(r"[＞>／/｜|＞＞]+|　{2,}| +", s)
    parts = [p for p in parts if p]
    if not parts:
        return ("","")
    # ルールに従い前半/後半へ
    n = len(parts)
    if n == 1:
        return (parts[0], "")
    if n == 2:
        left = parts[0]
        right = parts[1]
    elif n == 3:
        left = f"{parts[0]}　＋　{parts[1]}"
        right = parts[2]
    elif n == 4:
        left = f"{parts[0]}　＋　{parts[1]}"
        right = f"{parts[2]}　＋　{parts[3]}"
    elif n == 5:
        left = f"{parts[0]}　＋　{parts[1]}　＋　{parts[2]}"
        right = f"{parts[3]}　＋　{parts[4]}"
    else:
        left = f"{parts[0]}　＋　{parts[1]}　＋　{parts[2]}"
        right = f"{parts[3]}　＋　{parts[4]}　＋　{parts[5]}"
    return (left, right)

# ---- 建物語彙（検出強化用）----
BUILDING_TOKENS = (
    r"ビル|タワー|タワーズ|シティ|ヒルズ|スクエア|ガーデン|プレイス|"
    r"コート|テラス|センター|プラザ|レジデンス|マンション|ハイツ|"
    r"コーポ|メゾン|パーク|パレス|キャッスル|ステーション|モール|"
    r"パルコ|オフィス|ウォール|カレッジ|ドーム|ハウス|スタジアム"
)

# ---- 住所分割（v16 ロジック）----
def split_address(addr: str) -> tuple[str, str]:
    """
    v16 分割ロジック
      - 1-2-3-4 → 1-2-3 | 4（4は部屋番号のことが多い）
      - 「丁目-番-号」完了後に続く文字列は建物側へ
      - 番地直後が建物語（ビル/タワー/…/パルコ等）なら建物側へ
      - 「階/F/室/号室/内」が出たら、直前の番地ブロックで切る
      - 英語のみは 住所1=""、住所2=全塊
      - 出力はこのあと全角統一（to_zenkaku）で仕上げる
    """
    if addr is None:
        return ("", "")
    a = addr.strip()

    # 英語のみ → 住所2へ
    if re.fullmatch(r"[A-Za-z0-9\s,.\-/#()]+", a):
        return ("", a)

    # ハイフン等価
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

    # 1) 1-2-3-4 → 1-2-3 | 4
    m = re.search(rf"^(.*?)(\d+{H}\d+{H}\d+){H}(\d+)(.*)$", a)
    if m:
        head = (m.group(1) or "") + (m.group(2) or "")
        tail = (m.group(3) or "") + (m.group(4) or "")
        return (head, tail)

    # 2) 丁目・番・号 完了後 → 以降は建物
    m = re.search(rf"^(.*?\d+丁目\d+番\d+号)(.+)$", a)
    if m:
        return (m.group(1), m.group(2))

    # 3) 番地直後が建物名（建物語を含み、先頭が数字以外）なら分割
    mlast = _last_address_block(a)
    if mlast and mlast.end() < len(a):
        tail = a[mlast.end():]
        if re.match(r"^[^\d０-９]", tail):
            if re.search(BUILDING_TOKENS, tail, flags=re.IGNORECASE):
                return (a[:mlast.end()], tail)

    # 4) 「階/F/室/号室/内」出現時は、直前の番地ブロックで切る
    for tok in ["階", "F", "Ｆ", "室", "号室", "内"]:
        t = re.search(re.escape(tok), a)
        if t:
            mb = _last_address_block(a[:t.start()])
            if mb:
                return (a[:mb.end()], a[mb.end():])
            else:
                return (a[:t.start()], a[t.start():])

    # 5) デフォルト：分割不能
    return (a, "")

# ---- 住所の最終整形（全角統一、NHK内/大学構内などは住所2寄せ）----
def finalize_address(addr_raw: str) -> tuple[str, str]:
    if not addr_raw or not str(addr_raw).strip():
        return ("","")
    a1, a2 = split_address(str(addr_raw))
    # 全角統一
    a1 = to_zenkaku(a1)
    a2 = to_zenkaku(a2)
    # 「NHK内 / 大学構内 / センター内 / 工場内」などは住所2側へ寄せる
    SPECIAL = ["ＮＨＫ内","大学構内","センター内","工場内","構内","院内","校内"]
    for sp in SPECIAL:
        if sp in a1:
            a1 = a1.replace(sp, "")
            a2 = (a2 + sp).strip()
    # 余分スペース整理
    a1 = re.sub(r"　+", "　", a1).strip()
    a2 = re.sub(r"　+", "　", a2).strip()
    return (a1, a2)

# ---- ふりがな（簡易推定：ひらがな→カタカナ、英数は全角化。漢字のみは空欄可）----
def guess_kana(s: str) -> str:
    if not s:
        return ""
    # 会社名かなは法人語を除いてから
    s = re.sub(r"\s+", "", s)
    # ひらがな→カタカナ
    s_k = to_katakana_simple(s)
    # 既にカナが入っていればそれを採用、漢字しか無い場合は空欄
    has_kana = re.search(r"[ァ-ヴーｦ-ﾟぁ-ゖ]", s_k) is not None
    return s_k if has_kana else ""

def guess_company_kana(company: str) -> str:
    base = strip_corp_words(company or "")
    return guess_kana(base)

# ---- メイン変換 ----
def convert_row(eight_row: dict, custom_headers: list[str]) -> list[str]:
    # 基本項目
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

    # 住所1/2（全角統一は finalize_address 内で実施）
    addr1, addr2 = finalize_address(addr_raw)

    # 電話
    company_tel = join_phones([tel_company, tel_dept, tel_direct, fax, mobile])

    # 部署分割（全角）
    dept1, dept2 = split_department(dept)

    # 姓名/かな
    sei_kana = guess_kana(last)
    mei_kana = guess_kana(first)
    seimei = f"{last}{first}"
    seimei_kana = f"{sei_kana}{mei_kana}" if (sei_kana or mei_kana) else ""

    # 会社名かな
    company_kana = guess_company_kana(company)

    # メモ/備考（カスタム列: 値が "1" の列ヘッダを順番に）
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
    # 備考2/3 は今回未使用
    biko2 = ""
    biko3 = ""

    # 宛名職人の出力順に並べる
    out = [
        last,                       # 姓
        first,                      # 名
        sei_kana,                   # 姓かな
        mei_kana,                   # 名かな
        seimei,                     # 姓名
        seimei_kana,                # 姓名かな
        "",                         # ミドルネーム
        "",                         # ミドルネームかな
        "",                         # 敬称
        "",                         # ニックネーム
        "",                         # 旧姓
        "",                         # 宛先
        "",                         # 自宅〒
        "",                         # 自宅住所1
        "",                         # 自宅住所2
        "",                         # 自宅住所3
        "",                         # 自宅電話
        "",                         # 自宅IM ID
        "",                         # 自宅E-mail
        "",                         # 自宅URL
        "",                         # 自宅Social
        postal,                     # 会社〒
        addr1,                      # 会社住所1
        addr2,                      # 会社住所2
        "",                         # 会社住所3
        company_tel,                # 会社電話（; 連結）
        "",                         # 会社IM ID
        email,                      # 会社E-mail
        url,                        # 会社URL
        "",                         # 会社Social
        "", "", "", "", "", "", "", "",  # その他ブロック
        company_kana,               # 会社名かな
        company,                    # 会社名
        dept1,                      # 部署名1
        dept2,                      # 部署名2
        to_zenkaku(title) if title else "",  # 役職名（全角）
        "", "", "",                 # 連名系
        memo1, memo2, memo3, memo4, memo5,  # メモ1..5
        biko1, biko2, biko3,        # 備考1..3（備考1は改行区切り）
        "", "", "", "", ""          # 誕生日/性別/血液型/趣味/性格
    ]
    return out

def main():
    ap = argparse.ArgumentParser(description="Eight CSV → 宛名職人 CSV 変換ツール (v1.0)")
    ap.add_argument("-i", "--input", required=True, help="Eight 書き出しCSV (UTF-8)")
    ap.add_argument("-o", "--output", required=True, help="宛名職人用 出力CSV (UTF-8)")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    with in_path.open("r", encoding="utf-8", newline="") as f_in, \
         out_path.open("w", encoding="utf-8", newline="") as f_out:

        reader = csv.DictReader(f_in)
        # Eight のカラムを把握
        all_headers = reader.fieldnames or []
        if not all_headers:
            print("ERROR: 入力CSVのヘッダが読み取れません。", file=sys.stderr)
            sys.exit(1)

        # 固定ヘッダ + カスタムヘッダ
        fixed = EIGHT_FIXED_HEADER
        # 入力側の実ヘッダ順に基づき、固定以外をカスタムと見なす
        custom_headers = [h for h in all_headers if h not in fixed]

        writer = csv.writer(f_out)
        writer.writerow(ATENA_HEADER)

        for row in reader:
            out_row = convert_row(row, custom_headers)
            writer.writerow(out_row)

    print(f"Done. → {out_path}")

if __name__ == "__main__":
    main()
