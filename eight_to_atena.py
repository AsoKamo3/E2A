# -*- coding: utf-8 -*-
import io
import csv
import re
import unicodedata

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

# Eight 側の固定ヘッダ
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# 会社分類（カナ除外対象）
CORP_WORDS = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "相互会社", "清算株式会社",
    "一般社団法人", "一般財団法人", "公益社団法人", "公益財団法人",
    "特定非営利活動法人", "ＮＰＯ法人", "中間法人", "有限責任中間法人", "特例民法法人",
    "学校法人", "医療法人", "医療法人社団", "医療法人財団", "宗教法人", "社会福祉法人",
    "国立大学法人", "公立大学法人", "独立行政法人", "地方独立行政法人", "特殊法人",
    "有限責任事業組合", "投資事業有限責任組合", "特定目的会社", "特定目的信託"
]

# 建物名トリガー語（語頭から後ろを住所2へ）
BUILDING_TRIGGERS = [
    "ビルディング","タワービル","タワー","スクエア","レジデンス","ヒルズ","ホームズ",
    "シティ","ガーデン","プレイス","プレイスタワー","ハイツ","マンション","コート",
    "センター","ステーション","プラザ","パレス","ハウス","フォレスト","テラス","キャッスル",
    "コンプレックス","モール","ヒル","ヴィレッジ","ヴィラ","ハウジング","カレッジ","ホール"
]

# 住所2に寄せるキーワード
TAIL_FORCE_TO2 = ["階","Ｆ","F","号室","室", "内", "構内"]

# 半角→全角変換（ASCII・数字・ハイフン類を全角化）
def to_zenkaku(s: str) -> str:
    if not s:
        return s
    # いったんNFKCで正規化してから、ASCIIと数字を全角へ
    s = unicodedata.normalize("NFKC", s)
    # ハイフン類を全角長音符に統一
    s = re.sub(r"[-‐-‒–—―ｰ]", "－", s)
    out = []
    for ch in s:
        code = ord(ch)
        if 0x21 <= code <= 0x7E:  # ASCII可視文字
            out.append(chr(code + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)

# かな→カタカナ
def hira_to_kata(s: str) -> str:
    return "".join(chr(ord(ch)+0x60) if ("ぁ" <= ch <= "ゖ") else ch for ch in s)

# ローマ字→カタカナ（超簡易。漢字や混在は空欄返し）
_ROMA_MAP = {
    # 三文字
    "kyo":"キョ","kya":"キャ","kyu":"キュ","sho":"ショ","sha":"シャ","shu":"シュ",
    "cho":"チョ","cha":"チャ","chu":"チュ","nya":"ニャ","nyu":"ニュ","nyo":"ニョ",
    "hya":"ヒャ","hyu":"ヒュ","hyo":"ヒョ","mya":"ミャ","myu":"ミュ","myo":"ミョ",
    "rya":"リャ","ryu":"リュ","ryo":"リョ","gya":"ギャ","gyu":"ギュ","gyo":"ギョ",
    "ja":"ジャ","ju":"ジュ","jo":"ジョ","bya":"ビャ","byu":"ビュ","byo":"ビョ",
    "pya":"ピャ","pyu":"ピュ","pyo":"ピョ",
    # 二文字
    "ka":"カ","ki":"キ","ku":"ク","ke":"ケ","ko":"コ",
    "sa":"サ","shi":"シ","si":"シ","su":"ス","se":"セ","so":"ソ",
    "ta":"タ","chi":"チ","ti":"チ","tsu":"ツ","tu":"ツ","te":"テ","to":"ト",
    "na":"ナ","ni":"ニ","nu":"ヌ","ne":"ネ","no":"ノ",
    "ha":"ハ","hi":"ヒ","fu":"フ","hu":"フ","he":"ヘ","ho":"ホ",
    "ma":"マ","mi":"ミ","mu":"ム","me":"メ","mo":"モ",
    "ya":"ヤ","yu":"ユ","yo":"ヨ",
    "ra":"ラ","ri":"リ","ru":"ル","re":"レ","ro":"ロ",
    "wa":"ワ","wo":"ヲ","we":"ウェ","wi":"ウィ",
    "ga":"ガ","gi":"ギ","gu":"グ","ge":"ゲ","go":"ゴ",
    "za":"ザ","ji":"ジ","zu":"ズ","ze":"ゼ","zo":"ゾ",
    "da":"ダ","di":"ヂ","du":"ヅ","de":"デ","do":"ド",
    "ba":"バ","bi":"ビ","bu":"ブ","be":"ベ","bo":"ボ",
    "pa":"パ","pi":"ピ","pu":"プ","pe":"ペ","po":"ポ",
    # 一文字
    "a":"ア","i":"イ","u":"ウ","e":"エ","o":"オ","n":"ン"
}
def romaji_to_katakana(s: str) -> str:
    if not s:
        return ""
    if re.search(r"[^\sa-zA-Z\-']", s):
        # 漢字や記号混在は諦める（仕様上「ある程度の推測」でOK）
        return ""
    t = s.lower()
    t = re.sub(r"[^a-z]", " ", t)
    tokens = t.split()
    out = []
    for w in tokens:
        i = 0
        buf = ""
        while i < len(w):
            # 3文字優先
            if i+3 <= len(w) and w[i:i+3] in _ROMA_MAP:
                buf += _ROMA_MAP[w[i:i+3]]
                i += 3
            elif i+2 <= len(w) and w[i:i+2] in _ROMA_MAP:
                buf += _ROMA_MAP[w[i:i+2]]
                i += 2
            else:
                buf += _ROMA_MAP.get(w[i], "")
                i += 1
        out.append(buf)
    return "".join(out)

def guess_kana(s: str) -> str:
    if not s: return ""
    # ひらがな→カタカナ
    if re.fullmatch(r"[ぁ-ゖー・\s]+", s):
        return hira_to_kata(s)
    # カタカナならそのまま
    if re.fullmatch(r"[ァ-ヴー・\s]+", s):
        return s
    # 英字→ローマ字推測
    if re.fullmatch(r"[A-Za-z\s\.\-']+", s):
        return romaji_to_katakana(s)
    # 漢字含みは空欄（仕様：漢字は推測しない）
    return ""

def strip_corp_words(name: str) -> str:
    if not name: return ""
    out = name
    for w in CORP_WORDS:
        out = out.replace(w, "")
    return out.strip()

# 郵便番号：7桁→ xxx-xxxx
def normalize_postcode(s: str) -> str:
    if not s: return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return s  # そのまま返す

# 電話番号（複数は ; で連結、スペースなし）
def normalize_phone(s: str) -> str:
    if not s: return ""
    # 数字のみ抽出
    d = re.sub(r"\D", "", s)
    if not d: return ""
    # 携帯：070/080/090 → 3-4-4
    if re.match(r"^(070|080|090)\d{8}$", d):
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    # 市外局番 03/04/06 → 2-4-4
    if re.match(r"^(0[346])\d{8}$", d):
        return f"{d[:2]}-{d[2:6]}-{d[6:]}"
    # フリーダイヤル/ナビダイヤルなどは適当整形（3-3-4 を基本）
    if len(d) == 10:
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    if len(d) == 11:
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    return s  # よく分からない形式はそのまま

# 住所分割 v14/15/9 の統合版（日本語 + 一部英語表記）
def split_address(addr: str):
    """戻り値: (addr1, addr2) ともに最終的に全角"""
    if not addr or not addr.strip():
        return ("", "")

    a = addr.strip()

    # 英語のみ（日本語文字が一切ない） → 住所2に全塊
    if not re.search(r"[一-龯ぁ-ゖァ-ヴー々々〇ヶ〒]", a):
        return ("", to_zenkaku(a))

    # 「内」「構内」など以降は住所2へ寄せる（最初の出現位置から）
    for key in ["NHK内","大学構内","センター内","工場内","構内","内"]:
        m = re.search(re.escape(key), a)
        if m:
            left = a[:m.start()]
            right = a[m.start():]
            return (to_zenkaku(left), to_zenkaku(right))

    # 数字塊 1-2-3-4 → 1-2-3 / 4
    m = re.search(r"(\d+)[\-－–―ーｰ](\d+)[\-－–―ーｰ](\d+)[\-－–―ーｰ](\d+)", a)
    if m:
        before = a[:m.start()]
        d123 = m.group(0)
        tail = a[m.end():]
        addr1 = before + d123.rsplit(m.group(4), 1)[0].rstrip(" -－–―ーｰ")
        addr2 = m.group(4) + tail
        return (to_zenkaku(addr1), to_zenkaku(addr2))

    # 数字塊 1-2-3建物
    m = re.search(r"(\d+)[\-－–―ーｰ](\d+)[\-－–―ーｰ](\d+)(.+)$", a)
    if m:
        before = a[:m.start()]
        d123 = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        bname = m.group(4)
        return (to_zenkaku(before + d123), to_zenkaku(bname))

    # 3桁の番地（例：1-2-3 だけ）
    m = re.search(r"(\d+)[\-－–―ーｰ](\d+)[\-－–―ーｰ](\d+)$", a)
    if m:
        return (to_zenkaku(a), "")

    # 1-2 だけ
    m = re.search(r"(\d+)[\-－–―ーｰ](\d+)$", a)
    if m:
        return (to_zenkaku(a), "")

    # 建物トリガー語があれば、語頭から後ろを全部2へ
    for trig in BUILDING_TRIGGERS:
        m = re.search(re.escape(trig), a)
        if m:
            return (to_zenkaku(a[:m.start()]), to_zenkaku(a[m.start():]))

    # 「階/室」など
    for key in TAIL_FORCE_TO2:
        m = re.search(re.escape(key), a)
        if m:
            return (to_zenkaku(a[:m.start()]), to_zenkaku(a[m.start():]))

    # ここまでで分けられない → すべて住所1
    return (to_zenkaku(a), "")

# 部署名分割（前半/後半を2分割、スペースは全角）
def split_dept(dept: str):
    if not dept: return "",""
    # 階層区切り候補
    parts = re.split(r"[\/>|＞＞>|＞|＞\s\-・｜\|→→|→|⇒]|　", dept)
    parts = [p for p in parts if p.strip()]
    if not parts:
        return (to_zenkaku(dept), "")
    n = len(parts)
    if n == 1:
        return (to_zenkaku(parts[0]), "")
    # 前半・後半（2等分寄り）
    cut = n//2 if n%2==0 else (n//2+1)
    left = "　".join(parts[:cut])
    right = "　".join(parts[cut:])
    return (to_zenkaku(left), to_zenkaku(right))

# 電話5種を ; 連結
def join_phones(row):
    cands = []
    for k in ["TEL会社","TEL部門","TEL直通","Fax","携帯電話"]:
        v = row.get(k, "")
        v = normalize_phone(v)
        if v:
            cands.append(v)
    return ";".join(cands)

def eight_row_to_atena(row, custom_headers):
    # 名前
    sei = (row.get("姓") or "").strip()
    mei = (row.get("名") or "").strip()
    sei_kana = guess_kana(sei)
    mei_kana = guess_kana(mei)
    seimei = f"{sei}{mei}" if (sei or mei) else ""
    seimei_kana = f"{sei_kana}{mei_kana}" if (sei_kana or mei_kana) else ""

    # 郵便・住所
    pc = normalize_postcode(row.get("郵便番号",""))
    addr_raw = row.get("住所","")
    a1, a2 = split_address(addr_raw)  # ここで全角統一済

    # 会社
    company = (row.get("会社名") or "").strip()
    company_for_kana = strip_corp_words(company)
    company_kana = guess_kana(company_for_kana)

    # 部署
    dept1, dept2 = split_dept(row.get("部署名","") or "")

    # 役職
    title = row.get("役職","") or ""
    title = to_zenkaku(title)

    # 連絡先
    phone_joined = join_phones(row)
    email_company = row.get("e-mail","") or ""
    url_company = row.get("URL","") or ""

    # カスタムカラム（固定以降、値が "1" の見出し名をメモへ）
    memo_fields = []
    biko_over = []
    for h in custom_headers:
        v = (row.get(h) or "").strip()
        if v == "1":
            memo_fields.append(h)

    memos = (memo_fields[:5] + [""]*5)[:5]
    remains = memo_fields[5:]
    biko1 = "\n".join(remains) if remains else ""

    # atenaの並びで出力
    out = {
        "姓": sei,
        "名": mei,
        "姓かな": sei_kana,
        "名かな": mei_kana,
        "姓名": seimei,
        "姓名かな": seimei_kana,
        "ミドルネーム": "",
        "ミドルネームかな": "",
        "敬称": "",
        "ニックネーム": "",
        "旧姓": "",
        "宛先": "",
        "自宅〒": "",
        "自宅住所1": "",
        "自宅住所2": "",
        "自宅住所3": "",
        "自宅電話": "",
        "自宅IM ID": "",
        "自宅E-mail": "",
        "自宅URL": "",
        "自宅Social": "",
        "会社〒": pc,
        "会社住所1": a1,
        "会社住所2": a2,
        "会社住所3": "",
        "会社電話": phone_joined,
        "会社IM ID": "",
        "会社E-mail": email_company,
        "会社URL": url_company,
        "会社Social": "",
        "その他〒": "",
        "その他住所1": "",
        "その他住所2": "",
        "その他住所3": "",
        "その他電話": "",
        "その他IM ID": "",
        "その他E-mail": "",
        "その他URL": "",
        "その他Social": "",
        "会社名かな": company_kana,
        "会社名": to_zenkaku(company),
        "部署名1": dept1,
        "部署名2": dept2,
        "役職名": title,
        "連名": "",
        "連名ふりがな": "",
        "連名敬称": "",
        "連名誕生日": "",
        "メモ1": to_zenkaku(memos[0]),
        "メモ2": to_zenkaku(memos[1]),
        "メモ3": to_zenkaku(memos[2]),
        "メモ4": to_zenkaku(memos[3]),
        "メモ5": to_zenkaku(memos[4]),
        "備考1": to_zenkaku(biko1),
        "備考2": "",
        "備考3": "",
        "誕生日": "",
        "性別": "",
        "血液型": "",
        "趣味": "",
        "性格": "",
    }
    return out

def convert_eight_csv_to_atena_csv(csv_text: str) -> bytes:
    # 読み込み
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []

    # カスタム列（固定ヘッダ以降）
    custom_headers = [h for h in headers if h not in EIGHT_FIXED]

    # 出力
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ATENA_HEADER, lineterminator="\n")
    writer.writeheader()

    for row in reader:
        out = eight_row_to_atena(row, custom_headers)
        writer.writerow(out)

    data = buf.getvalue().encode("utf-8")
    return data
