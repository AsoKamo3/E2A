# app.py
# Eight → 宛名職人 変換 最小版 v1.0
# 単一ファイル。POST /convert で直接 CSV を返します。

import io
import csv
import re
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort

VERSION = "v1.0"

# ====== 宛名職人ヘッダ ======
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

# ====== Eight 固定カラム（この順で存在する想定） ======
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

# ====== 建物キーワード（語が出たら以降は建物扱い） ======
BLDG_WORDS = [
    "ビルディング","タワービル","タワー","ヒルズ","スクエア","センター","シティ","シティタワー",
    "ガーデン","ガーデンタワー","トリトン","プレイス","レジデンス","コート","パーク","ステーション",
    "プラザ","フォレスト","テラス","ハイツ","マンション","コーポ","レジデンシャル","ハウス",
    "アネックス","ANNEX","アーバン","ゲート","ゲートシティ","ドーム","ドミール","シャトレ",
    "オフィス","ウェスト","イースト","ノース","サウス","ターミナル","スクウェア","スクエア",
    "スタジアム","スタジアムプレイス","パレス","キャッスル","カレッジ","カンファレンス",
    "MRビル","ビル","Bldg.","Bldg", "BLDG", "BLDG.", "Tower", "TOWER"
]
# 階・室トリガ（出現以降は建物へ寄せる）
FLOOR_ROOM = ["階","Ｆ","F","フロア","室","号","B1","B2","Ｂ１","Ｂ２"]

# ====== ひら→カタカナ（kanjiは読めないので外部ツール任せ） ======
def to_katakana_guess(s: str) -> str:
    if not s:
        return ""
    # かな → カタカナ
    hira2kata = str.maketrans(
        {chr(i): chr(i + 0x60) for i in range(0x3041, 0x3097)}
    )
    t = s.translate(hira2kata)
    # 追加の推測（漢字は読めない）→ 残存漢字が多ければ空欄のまま
    # 必要なら pykakasi を使う（任意）
    try:
        import pykakasi
        kks = pykakasi.kakasi()
        res = "".join([r["kana"] for r in kks.convert(s)])
        return res.translate(hira2kata)
    except Exception:
        return t if re.search(r"[ぁ-ん]", s) else ""

# ====== 全角統一 ======
# 記号・英数字・ダッシュの混在を全角化（住所1/2の最終出力に適用）
def to_zenkaku(s: str) -> str:
    if not s:
        return ""
    # 半角→全角（英数・記号）
    # Python標準での網羅変換はないので簡易置換＋ダッシュ正規化
    import unicodedata
    # ひとまずNFKCで統一→ダッシュ類を全角長音符に寄せる→英数記号を全角近似
    t = unicodedata.normalize("NFKC", s)
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)  # ダッシュ系を全角ハイフン風に
    # アルファベット・数字を全角へ
    def to_wide_char(ch):
        code = ord(ch)
        # 0-9
        if 0x30 <= code <= 0x39:
            return chr(code + 0xFEE0)
        # A-Z
        if 0x41 <= code <= 0x5A:
            return chr(code + 0xFEE0)
        # a-z
        if 0x61 <= code <= 0x7A:
            return chr(code + 0xFEE0)
        # 記号の一部
        table = {
            "/":"／", "#":"＃", "+":"＋", ".":"．", ",":"，", ":":"：",
            "(": "（", ")":"）", "[":"［", "]":"］", "&":"＆", "@":"＠",
            "~":"～", "_":"＿", "'":"’", '"':"”", "%":"％"
        }
        return table.get(ch, ch)
    t = "".join(to_wide_char(c) for c in t)
    return t

# ====== 郵便番号を xxx-xxxx へ ======
def normalize_postcode(s: str) -> str:
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s  # 既に xxx-xxxx などはそのまま

# ====== 電話番号の正規化＆結合 ======
def normalize_phone(*nums):
    cleaned = []
    for n in nums:
        if not n:
            continue
        d = re.sub(r"\D", "", n)
        if not d:
            continue
        # 携帯 070/080/090 → 3-4-4
        if re.match(r"^(070|080|090)\d{8}$", d):
            cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        # 市外局番 03,04,06 → 2-4-4（04は本来可変だが簡略）
        if re.match(r"^(0[346])\d{8}$", d):
            cleaned.append(f"{d[:2]}-{d[2:6]}-{d[6:]}")
            continue
        # NTT標準（ざっくり） 0AA-BBBB-CCCC / 0AAA-BBB-CCCC などは長さで分岐
        if d.startswith("0") and len(d) in (10,11):
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        # その他は原形にハイフン挿入せずそのまま
        cleaned.append(n)
    # セミコロン連結（スペースなし）
    return ";".join(cleaned)

# ====== 部署の2分割（前半/後半）・全角スペース結合 ======
def split_department(dept: str):
    if not dept:
        return "", ""
    # 階層セパレータ候補
    parts = re.split(r"[\/>＞＞＞＞]|[\s　]*>[>\s　]*|[\s　]*\/[\s　]*|[\s　]*\|[\s　]*", dept)
    parts = [p for p in (p.strip() for p in parts) if p]
    if not parts:
        return to_zenkaku(dept), ""
    n = len(parts)
    k = (n + 1) // 2  # 前半に多め
    left = "　".join(to_zenkaku(p) for p in parts[:k])
    right = "　".join(to_zenkaku(p) for p in parts[k:])
    return left, right

# ====== 英文住所は住所1空欄・全部を住所2 ======
def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    # 日本語っぽい文字が一切無く、英数・空白・記号主体なら英文扱い
    return not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr) and re.search(r"[A-Za-z]", addr)

# ====== 住所分割（v14 相当・確定ルール） ======
def split_address(addr: str):
    if not addr:
        return "", ""
    s = addr.strip()

    # 英文は住所1空欄で全塊を住所2
    if is_english_only(s):
        return "", to_zenkaku(s)

    # 「NHK内/大学構内/センター内/工場内」などは以降まとめて住所2
    inside_tokens = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|内)"
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        left = s[:m_inside.start()]
        right = s[m_inside.start():]
        return to_zenkaku(left), to_zenkaku(right)

    # 基本：先頭から「…数字1-数字2-数字3」までが住所1、以降（建物語＋階室含む）は住所2
    # 可変のダッシュに対応
    dash = r"[‐-‒–—―ｰ\-−]"
    num = r"[0-9０-９]+"
    # 最長で 1-2-3-4（4は部屋番号のことが多い）
    # パターン1: ～ 1-2-3-4 建物/無し（4があれば4は住所2へ）
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = m.group("tail") or ""
        # tail に建物語先頭があるなら丸ごと住所2。無ければ room/tail を見て判断
        if tail:
            # 建物語 or 階・室が出たら以降は住所2
            if any(w in tail for w in BLDG_WORDS) or any(t in tail for t in FLOOR_ROOM):
                return to_zenkaku(base), to_zenkaku((room and room) + tail)
            # 建物語が base 側に連結しているパターン（例：…15桑野ビル2F）
            for w in BLDG_WORDS:
                idx = base.find(w)
                if idx >= 0:
                    # …15／桑野ビル2F へ
                    return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)
        # tail が空でも room があれば住所2へ
        if room:
            return to_zenkaku(base), to_zenkaku(room)
        # ここまで来たら全て住所1（建物なし）
        return to_zenkaku(s), ""

    # パターン2: ～ 1-2-3建物名（ダッシュ3つ目の後が建物）
    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    # パターン3: ～ 1-2建物名
    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        return to_zenkaku(m3.group("pre")), to_zenkaku(m3.group("bldg"))

    # パターン4: ～ 1丁目2番3号（＋任意）
    p4 = re.compile(rf"^(?P<pre>.*?{num}丁目{num}番{num}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    # どれでもない：建物語キーワードの最初の出現位置で二分
    for w in BLDG_WORDS:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 最後の保険：階/室ワードが出たらそこで二分
    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            # その語の手前までを住所1、以降を住所2
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    # 分割不能 → 住所1に全て
    return to_zenkaku(s), ""

# ====== Eight→宛名職人 変換（テキスト→テキスト） ======
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    # 入力を方眼的に読む（タブ/カンマ混在を許容）
    # ここでは Eight の CSV を想定：カンマ区切り・UTF-8
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []

    for row in reader:
        # 固定カラム取り出し（存在しなくても KeyError は出さず空文字）
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

        # 会社電話（; 連結）
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)

        # 部署 2 分割（全角スペース結合）
        dept1, dept2 = split_department(dept)

        # 姓名
        full_name = f"{last}{first}"
        full_name_kana = ""  # 未確定：かな自動は任意（pykakasiがあれば）
        last_kana = to_katakana_guess(last)
        first_kana = to_katakana_guess(first)

        # 会社名かな（会社種別は除外）
        company_for_kana = company
        for t in COMPANY_TYPES:
            company_for_kana = company_for_kana.replace(t, "")
        company_kana = to_katakana_guess(company_for_kana)

        # カスタムカラム（固定以降で '1' のヘッダ名をメモ1..5/備考1 へ）
        memo = ["", "", "", "", ""]
        biko = ""
        # DictReaderのfieldnamesで順序を参照
        for hdr in (reader.fieldnames or [])[len(EIGHT_FIXED):]:
            val = (row.get(hdr, "") or "").strip()
            if val == "1":
                # 空いているメモ枠へ
                for i in range(5):
                    if not memo[i]:
                        memo[i] = hdr
                        break
                else:
                    biko += (("\n" if biko else "") + hdr)

        out = [
            last, first,                   # 姓, 名
            last_kana, first_kana,         # 姓かな, 名かな
            full_name, full_name_kana,     # 姓名, 姓名かな
            "", "", "",                    # ミドル/敬称
            "", "", "",                    # ニック/旧姓/宛先
            "", "", "", "", "",            # 自宅系（未使用）
            "", "", "", "",                # 自宅続き
            postcode, addr1, addr2, "",    # 会社〒, 会社住所1, 会社住所2, 会社住所3
            phone_join, "", email,         # 会社電話, 会社IM, 会社E-mail
            url, "",                       # 会社URL, 会社Social
            "", "", "", "", "", "", "", "",# その他系（未使用）
            company_kana, company,         # 会社名かな, 会社名
            dept1, dept2,                  # 部署名1, 部署名2
            title,                         # 役職名
            "", "", "", "",                # 連名系
            memo[0], memo[1], memo[2], memo[3], memo[4],   # メモ1..5
            biko, "", "",                  # 備考1..3
            "", "", "", ""                 # 誕生日, 性別, 血液型, 趣味, 性格
        ]
        rows.append(out)

    # 書き出し
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows)
    return buf.getvalue()

# ====== Web: 超簡易UI（Jinja文字列） ======
INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>Eight → 宛名職人 変換 ({{version}})</title>
  <style>
    body { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, "Noto Sans JP", sans-serif; padding: 24px; }
    .card { max-width: 720px; margin: 0 auto; padding: 24px; border: 1px solid #ddd; border-radius: 12px; }
    h1 { font-size: 20px; margin-top: 0; }
    input[type=file] { margin: 12px 0; }
    button { padding: 10px 16px; border: 0; border-radius: 8px; background: #0b6; color: #fff; font-weight: 600; cursor: pointer; }
    .muted { color: #666; font-size: 12px; }
    .ver { font-size: 12px; color: #444; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Eight → 宛名職人 変換 <span class="ver">({{version}})</span></h1>
    <form method="post" action="/convert" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv" required />
      <div class="muted">UTF-8 / カンマ区切りの Eight CSV を選択してください。</div>
      <p><button type="submit">変換してダウンロード</button></p>
    </form>
  </div>
</body>
</html>
"""

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML, version=VERSION)

@app.route("/convert", methods=["POST"])
def convert():
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        abort(400, "CSVファイルが選択されていません。")
    try:
        csv_text = f.stream.read().decode("utf-8")
    except UnicodeDecodeError:
        abort(400, "文字コードは UTF-8 にしてください。")

    try:
        out_csv_text = convert_eight_csv_text_to_atena_csv_text(csv_text)
    except Exception as e:
        abort(500, f"変換に失敗しました: {e}")

    buf = io.BytesIO(out_csv_text.encode("utf-8"))
    filename = f"atena_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        buf,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=filename,
        max_age=0,
        etag=False,
        conditional=False,
        last_modified=None,
    )

@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
