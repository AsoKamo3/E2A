# utils/textnorm.py
# 文字種統一・郵便/電話正規化・部署分割・かな推定・ヘッダ定義

import re
import unicodedata

# ===== 宛名職人ヘッダ =====
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

# ===== Eight 固定カラム =====
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# ===== 会社種別（かな除外対象） =====
COMPANY_TYPES = [
    "株式会社","有限会社","合同会社","合資会社","合名会社","相互会社","清算株式会社",
    "一般社団法人","一般財団法人","公益社団法人","公益財団法人",
    "特定非営利活動法人","ＮＰＯ法人","中間法人","有限責任中間法人","特例民法法人",
    "学校法人","医療法人","医療法人社団","医療法人財団","宗教法人","社会福祉法人",
    "国立大学法人","公立大学法人","独立行政法人","地方独立行政法人","特殊法人",
    "有限責任事業組合","投資事業有限責任組合","特定目的会社","特定目的信託"
]

# ===== 全角統一 =====
def to_zenkaku(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)  # ダッシュ系を全角に寄せる
    def to_wide_char(ch):
        code = ord(ch)
        if 0x30 <= code <= 0x39:  # 0-9
            return chr(code + 0xFEE0)
        if 0x41 <= code <= 0x5A:  # A-Z
            return chr(code + 0xFEE0)
        if 0x61 <= code <= 0x7A:  # a-z
            return chr(code + 0xFEE0)
        table = {
            "/":"／", "#":"＃", "+":"＋", ".":"．", ",":"，", ":":"：",
            "(": "（", ")":"）", "[":"［", "]":"］", "&":"＆", "@":"＠",
            "~":"～", "_":"＿", "'":"’", '"':"”", "%":"％"
        }
        return table.get(ch, ch)
    return "".join(to_wide_char(c) for c in t)

# ===== 郵便番号 → xxx-xxxx =====
def normalize_postcode(s: str) -> str:
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s

# ===== 電話番号 正規化＆連結（;区切り） =====
def normalize_phone(*nums):
    cleaned = []
    for n in nums:
        if not n:
            continue
        d = re.sub(r"\D", "", n)
        if not d:
            continue
        if re.match(r"^(070|080|090)\d{8}$", d):  # 携帯
            cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        if re.match(r"^(0[346])\d{8}$", d):       # 03/04/06系
            cleaned.append(f"{d[:2]}-{d[2:6]}-{d[6:]}")
            continue
        if d.startswith("0") and len(d) in (10, 11):  # 固定電話ざっくり
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        cleaned.append(n)
    return ";".join(cleaned)

# ===== 部署の2分割 =====
def split_department(dept: str):
    if not dept:
        return "", ""
    parts = re.split(r"[\/>＞＞＞＞]|[\s　]*>[>\s　]*|[\s　]*\/[\s　]*|[\s　]*\|[\s　]*", dept)
    parts = [p for p in (p.strip() for p in parts) if p]
    if not parts:
        return to_zenkaku(dept), ""
    n = len(parts)
    k = (n + 1) // 2
    left = "　".join(to_zenkaku(p) for p in parts[:k])
    right = "　".join(to_zenkaku(p) for p in parts[k:])
    return left, right

# ===== かな推定 =====
def to_katakana_guess(s: str) -> str:
    if not s:
        return ""
    # ひらがな→カタカナ
    hira2kata = str.maketrans({chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)})
    base = s.translate(hira2kata)
    try:
        import pykakasi
        kks = pykakasi.kakasi()
        res = "".join([r["kana"] for r in kks.convert(s)])
        return res.translate(hira2kata)
    except Exception:
        return base if re.search(r"[ぁ-ん]", s) else ""
