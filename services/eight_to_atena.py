# services/eight_to_atena.py
# Eight CSV/TSV → 宛名職人CSV 変換本体
from __future__ import annotations

import io
import csv
import math
import re
from typing import List

from converters.address import split_address
from utils.textnorm import to_zenkaku_wide, normalize_postcode
from utils.jp_area_codes import AREA_CODES, __version__ as AREACODE_VER  # 参照のみ（/healthz表示は app.py 側）

__version__ = "v2.25"

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

EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ====== ユーティリティ ======
def _clean_key(k: str) -> str:
    return (k or "").lstrip("\ufeff").strip()

def _clean_row(row: dict) -> dict:
    return {_clean_key(k): (v or "") for k, v in row.items()}

# 部署の「前半/後半」分割（区切り：スペース/スラッシュ/中点/読点など）
SEP_PATTERN = re.compile(r'(?:／|/|・|,|、|｜|\||\s)+')
def _split_department_half(s: str) -> tuple[str, str]:
    s = (s or "").strip()
    if not s:
        return "", ""
    tokens = [t for t in SEP_PATTERN.split(s) if t]
    if len(tokens) <= 1:
        return s, ""
    n = len(tokens)
    k = math.ceil(n / 2.0)
    left = "　".join(tokens[:k])     # 全角スペースで結合
    right = "　".join(tokens[k:]) if k < n else ""
    return left, right

# ====== 電話整形（最長一致＋欠落0補正＋携帯3-4-4） ======
_MOBILE_PREFIXES = ("070", "080", "090")

def _digits_ascii(s: str) -> str:
    """全角/半角を問わず『数字だけ』を抽出（Unicodeの数字もOK）。"""
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _is_service_or_special(d: str) -> bool:
    """0120, 0800, 0570, 050 等はそのままにする（体裁だけ）。"""
    return d.startswith(("0120", "0800", "0570", "050"))

def _format_mobile(d: str) -> str:
    # 11桁携帯 → 3-4-4
    if len(d) == 11:
        return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"
    # 10桁で先頭0欠落（70/80/90）→ 0を補い 3-4-4
    if len(d) == 10 and d.startswith(("70","80","90")):
        d = "0" + d
        return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"
    return d

def _format_by_area_longest(d: str) -> str:
    """'0' から始まる固定電話 d を AREA_CODES の最長一致でハイフン挿入。"""
    ac = None
    for code in AREA_CODES:  # 5桁→2桁の順に最長一致
        if d.startswith(code):
            ac = code
            break
    if not ac:
        # フォールバック：03/06 は 2-4-4、それ以外は 3-3-4
        if len(d) == 10 and d.startswith(("03","06")):
            return f"{d[0:2]}-{d[2:6]}-{d[6:10]}"
        if len(d) == 10:
            return f"{d[0:3]}-{d[3:6]}-{d[6:10]}"
        return d

    local = d[len(ac):]
    # 汎用ルール（局番長に応じた分割）
    if len(d) == 10:
        if len(ac) == 2:   # 03 / 06
            return f"{ac}-{local[0:4]}-{local[4:8]}"
        elif len(ac) == 3:
            return f"{ac}-{local[0:3]}-{local[3:7]}"
        elif len(ac) == 4:
            return f"{ac}-{local[0:3]}-{local[3:6]}"
        elif len(ac) == 5:
            return f"{ac}-{local[0:2]}-{local[2:5]}"
    return d

def _normalize_one_phone(raw: str) -> str:
    """単一フィールドを正規化。空or無効は空文字で返す。"""
    if not raw or not raw.strip():
        return ""
    d = _digits_ascii(raw)
    if not d:
        return ""

    # サービス/特番系は体裁だけ（0120/0800/0570/050 ...）
    if _is_service_or_special(d):
        # 0120-XXX-XXX / 0800-XXX-XXXX / 0570-XXX-XXX / 050-XXXX-XXXX （おおまか体裁）
        if d.startswith("0120") and len(d) == 10:
            return f"{d[0:4]}-{d[4:7]}-{d[7:10]}"
        if d.startswith("0800") and len(d) == 11:
            return f"{d[0:4]}-{d[4:7]}-{d[7:11]}"
        if d.startswith("0570") and len(d) == 10:
            return f"{d[0:4]}-{d[4:7]}-{d[7:10]}"
        if d.startswith("050") and len(d) == 11:
            return f"{d[0:3]}-{d[3:7]}-{d[7:11]}"
        return d  # 長さが想定外ならそのまま

    # 携帯系（11桁 or 10桁で70/80/90始まり）
    if (len(d) == 11 and d.startswith(_MOBILE_PREFIXES)) or (len(d) == 10 and d.startswith(("70","80","90"))):
        return _format_mobile(d)

    # 固定電話：9桁は「先頭0欠落」とみなして補う（例: 3-5724-8523 → 03-5724-8523）
    if len(d) == 9:
        d = "0" + d

    # 固定の標準は 10桁（0始まり）。最長一致で体裁。
    if len(d) == 10 and d.startswith("0"):
        return _format_by_area_longest(d)

    # それ以外（桁不明など）は安全側で元数字のまま
    return d

def _normalize_phone(*nums: str) -> str:
    """
    引数の電話フィールド群を正規化し、空でないものを ';' 連結。
    - 前後空白/全角ダッシュ混在/重複除去に対応
    """
    parts: List[str] = []
    for raw in nums:
        s = _normalize_one_phone(raw)
        if s:
            parts.append(s)

    # 重複除去（順序維持）
    seen = set()
    uniq: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    return ";".join(uniq)

# ====== 変換本体 ======
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    # CSV/TSV 自動判定
    buf = io.StringIO(csv_text)
    sample = buf.read(4096)
    buf.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t"])
    except Exception:
        class _D: delimiter = ","
        dialect = _D()
    reader = csv.DictReader(buf, dialect=dialect)
    reader.fieldnames = [_clean_key(h) for h in (reader.fieldnames or [])]

    rows_out: List[List[str]] = []

    for raw in reader:
        row = _clean_row(raw)
        g = lambda k: (row.get(_clean_key(k), "") or "").strip()

        # 入力
        company_raw = g("会社名")
        dept_raw    = g("部署名")
        title_raw   = g("役職")
        last        = g("姓")
        first       = g("名")
        email       = g("e-mail")
        postcode    = normalize_postcode(g("郵便番号"))   # ###-####
        addr_raw    = g("住所")
        tel_company = g("TEL会社")
        tel_dept    = g("TEL部門")
        tel_direct  = g("TEL直通")
        fax         = g("Fax")
        mobile      = g("携帯電話")
        url         = g("URL")

        # 住所分割（split が建物を拾えなければ住所1に原文維持）
        a1, a2 = split_address(addr_raw)
        if (a2 or "").strip():
            addr1_raw, addr2_raw = a1, a2
        else:
            addr1_raw, addr2_raw = addr_raw, ""

        # 電話（← ここがポイント：新しい正規化を使用）
        phone_join = _normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署（前半/後半）
        dept1_raw, dept2_raw = _split_department_half(dept_raw)

        # 全角ワイド化（住所/社名/部署/役職）
        addr1 = to_zenkaku_wide(addr1_raw)
        addr2 = to_zenkaku_wide(addr2_raw)
        company = to_zenkaku_wide(company_raw)
        dept1 = to_zenkaku_wide(dept1_raw)
        dept2 = to_zenkaku_wide(dept2_raw)
        title = to_zenkaku_wide(title_raw)

        # 姓名（かなは現状空）
        full_name = f"{last}{first}"
        last_kana = ""
        first_kana = ""
        full_name_kana = ""
        company_kana = ""

        # メモ/備考（固定以降の '1' を拾う）
        fn_clean = reader.fieldnames or []
        tail_headers = fn_clean[len(EIGHT_FIXED):]
        flags: List[str] = []
        for hdr in tail_headers:
            val = (row.get(hdr, "") or "").strip()
            if val in ("1", "1.0", "TRUE", "True", "true"):
                flags.append(hdr)
        memo = ["", "", "", "", ""]
        biko = ""
        for i, hdr in enumerate(flags):
            if i < 5:
                memo[i] = hdr
            else:
                biko += (("\n" if biko else "") + hdr)

        # 出力
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
            "", "", "", "", "", "", "", "", "",
            company_kana, company,
            dept1, dept2,
            title,
            "", "", "", "",
            memo[0], memo[1], memo[2], memo[3], memo[4],
            biko, "", "",
            "", "", "", "", ""
        ]

        if len(out_row) != len(ATENA_HEADERS):
            raise ValueError(f"出力列数がヘッダと不一致: row={len(out_row)} headers={len(ATENA_HEADERS)}")

        rows_out.append(out_row)

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows_out)
    return out.getvalue()
