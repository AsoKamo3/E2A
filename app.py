# app.py
# Eight → 宛名職人 変換 最小版 v1.6
# 単一ファイル運用のまま、以下を追加:
# - 構造化ログ / Gunicorn連携
# - /version エンドポイント
# - bldg_words.json ホットリロード (/reload-bldg + 画面ボタン)
# - ふりがな自動付与を外部モジュール化（furigana.py）＆環境変数でON/OFF

import io
import os
import csv
import re
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, request, render_template_string, send_file, abort, jsonify, g

from furigana import to_katakana_guess  # 分離モジュール（有効/無効は内部で判定）

VERSION = "v1.6"
APP_STARTED_AT = datetime.utcnow().isoformat() + "Z"
HERE = Path(__file__).resolve().parent
BLDG_JSON_PATH = HERE / "bldg_words.json"

# ====== ログ設定（Gunicornと統合） ======
def setup_logging():
    gunicorn_error = logging.getLogger("gunicorn.error")
    root = logging.getLogger()
    if gunicorn_error.handlers:
        root.handlers = gunicorn_error.handlers
        root.setLevel(gunicorn_error.level)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

setup_logging()
logger = logging.getLogger(__name__)

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

# ====== Eight 固定カラム ======
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

# ====== （初回ロード用のデフォルト値：万一JSONが読めない場合の保険） ======
DEFAULT_BLDG_WORDS = [
    "ANNEX","Bldg","BLDG","Bldg.","BLDG.","CABO","MRビル","Tower","TOWER",
    "Trestage","アーバン","アネックス","イースト","ヴィラ","ウェスト","エクレール",
    "オフィス","オリンピア","ガーデン","ガーデンタワー","カミニート","カレッジ",
    "カンファレンス","キャッスル","キング","クルーセ","ゲート","ゲートシティ","コート",
    "コープ","コーポ","サウス","シティ","シティタワー","シャトレ","スクウェア","スクエア",
    "スタジアム","スタジアムプレイス","ステーション","センター","セントラル","ターミナル",
    "タワー","タワービル","テラス","ドーム","ドミール","トリトン","ノース","パーク",
    "ハイツ","ハウス","パルテノン","パレス","ビル","ヒルズ","ビルディング","フォレスト",
    "プラザ","プレイス","プレステージュ","フロント","ホームズ","マンション","レジデンシャル",
    "レジデンス","構内","倉庫"
]

# 階・室トリガ（出現以降は建物へ寄せる）
FLOOR_ROOM = ["階","Ｆ","F","フロア","室","号","B1","B2","Ｂ１","Ｂ２"]

# ====== Flask アプリ ======
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MBまで

# bldg_words の状態をアプリ設定に保持
def load_bldg_words():
    try:
        data = json.loads(BLDG_JSON_PATH.read_text(encoding="utf-8"))
        words = data.get("BLDG_WORDS") if isinstance(data, dict) else data
        words = list(dict.fromkeys([str(w) for w in (words or [])]))  # 重複除去/文字列化
        if not words:
            raise ValueError("bldg_words.json に有効な語がありません。")
        app.config["BLDG_WORDS"] = words
        app.config["BLDG_LAST_LOADED"] = datetime.utcnow().isoformat() + "Z"
        logger.info("bldg_words.json reloaded: %d words", len(words))
    except Exception as e:
        # 失敗時はデフォルトにフォールバック（起動継続）
        app.config["BLDG_WORDS"] = DEFAULT_BLDG_WORDS
        app.config["BLDG_LAST_LOADED"] = datetime.utcnow().isoformat() + "Z"
        logger.error("Failed to load bldg_words.json: %s (fallback to default, %d words)",
                     e, len(DEFAULT_BLDG_WORDS))

load_bldg_words()  # 起動時ロード

def get_bldg_words():
    return app.config.get("BLDG_WORDS", DEFAULT_BLDG_WORDS)

# ====== かな推定を有効化するか（環境変数で切替） ======
# furigana.to_katakana_guess 内部で参照するため、環境変数で制御
os.environ.setdefault("FURIGANA_ENABLED", "1")  # 有効: "1" / 無効: "0"

# ====== 全角統一 ======
def to_zenkaku(s: str) -> str:
    if not s:
        return ""
    import unicodedata
    t = unicodedata.normalize("NFKC", s)
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)  # ダッシュ類を全角に
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

# ====== 郵便番号 / 電話 ======
def normalize_postcode(s: str) -> str:
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s

def normalize_phone(*nums):
    cleaned = []
    for n in nums:
        if not n:
            continue
        d = re.sub(r"\D", "", n)
        if not d:
            continue
        if re.match(r"^(070|080|090)\d{8}$", d):
            cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        if re.match(r"^(0[346])\d{8}$", d):
            cleaned.append(f"{d[:2]}-{d[2:6]}-{d[6:]}")
            continue
        if d.startswith("0") and len(d) in (10,11):
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        cleaned.append(n)
    return ";".join(cleaned)

# ====== 部署2分割 ======
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

# ====== 英文住所判定 ======
def is_english_only(addr: str) -> bool:
    if not addr:
        return False
    return not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr) and re.search(r"[A-Za-z]", addr)

# ====== 丁目・番・号・「の」→ ハイフン正規化 ======
def normalize_block_notation(s: str) -> str:
    if not s:
        return s
    znum = r"[0-9０-９]+"
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番(?!地)", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*の\s*({znum})", r"\1-\2", s)
    return s

# ====== 住所分割（v17 相当） ======
def split_address(addr: str):
    if not addr:
        return "", ""
    s = addr.strip()
    s = normalize_block_notation(s)

    if is_english_only(s):
        return "", to_zenkaku(s)

    inside_tokens = r"(?:ＮＨＫ内|NHK内|大学構内|センター内|工場内|構内|キャンパス内|病院内|庁舎内|体育館内|美術館内|博物館内)"
    m_inside = re.search(inside_tokens, s)
    if m_inside:
        left = s[:m_inside.start()]
        right = s[m_inside.start():]
        return to_zenkaku(left), to_zenkaku(right)

    dash = r"[‐-‒–—―ｰ\-−]"
    num  = r"[0-9０-９]+"

    # 1-2-3(-4) + tail
    p = re.compile(rf"^(?P<base>.*?{num}{dash}{num}{dash}{num})(?:{dash}(?P<room>{num}))?(?P<tail>.*)$")
    m = p.match(s)
    if m:
        base = m.group("base")
        room = m.group("room") or ""
        tail = (m.group("tail") or "")
        tail_stripped = tail.lstrip()
        BLDG_WORDS = get_bldg_words()

        if re.match(r"^[\s　]+", tail) and tail_stripped:
            if (any(w in tail_stripped for w in BLDG_WORDS) or
                any(t in tail_stripped for t in FLOOR_ROOM) or
                re.search(inside_tokens, tail_stripped) or
                re.match(r"^[^\d０-９]", tail_stripped)):
                return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        if tail_stripped and (any(w in tail_stripped for w in BLDG_WORDS) or any(t in tail_stripped for t in FLOOR_ROOM)):
            return to_zenkaku(base), to_zenkaku((room or "") + tail_stripped)

        for w in sorted(BLDG_WORDS, key=len, reverse=True):
            idx = base.find(w)
            if idx >= 0:
                return to_zenkaku(base[:idx]), to_zenkaku(base[idx:] + (room or "") + tail)

        if room:
            return to_zenkaku(base), to_zenkaku(room)
        return to_zenkaku(s), ""

    p2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})(?P<bldg>.+)$")
    m2 = p2.match(s)
    if m2:
        return to_zenkaku(m2.group("pre")), to_zenkaku(m2.group("bldg"))

    p3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})(?P<bldg>.+)$")
    m3 = p3.match(s)
    if m3:
        return to_zenkaku(m3.group("pre")), to_zenkaku(m3.group("bldg"))

    p_space3 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space3 = p_space3.match(s)
    if m_space3:
        return to_zenkaku(m_space3.group("pre")), to_zenkaku(m_space3.group("bldg"))

    p_space2 = re.compile(rf"^(?P<pre>.*?{num}{dash}{num})[\s　]+(?P<bldg>.+)$")
    m_space2 = p_space2.match(s)
    if m_space2:
        return to_zenkaku(m_space2.group("pre")), to_zenkaku(m_space2.group("bldg"))

    p4 = re.compile(rf"^(?P<pre>.*?{num}丁目{num}番{num}号)(?P<bldg>.*)$")
    m4 = p4.match(s)
    if m4:
        return to_zenkaku(m4.group("pre")), to_zenkaku(m4.group("bldg"))

    BLDG_WORDS = get_bldg_words()
    for w in sorted(BLDG_WORDS, key=len, reverse=True):
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    for w in FLOOR_ROOM:
        idx = s.find(w)
        if idx > 0:
            return to_zenkaku(s[:idx]), to_zenkaku(s[idx:])

    return to_zenkaku(s), ""

# ====== Eight→宛名職人 変換 ======
def convert_eight_csv_text_to_atena_csv_text(csv_text: str) -> str:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []

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

        addr1, addr2 = split_address(addr_raw)
        phone_join = normalize_phone(tel_company, tel_dept, tel_direct, fax, mobile)
        dept1, dept2 = split_department(dept)

        full_name = f"{last}{first}"
        full_name_kana = ""
        last_kana = to_katakana_guess(last)   # ← 切替はモジュール側で吸収
        first_kana = to_katakana_guess(first)

        company_for_kana = company
        for t in COMPANY_TYPES:
            company_for_kana = company_for_kana.replace(t, "")
        company_kana = to_katakana_guess(company_for_kana)

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

        out = [
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
            dept1, dept2,
            title,
            "", "", "", "",
            memo[0], memo[1], memo[2], memo[3], memo[4],
            biko, "", "",
            "", "", "", ""
        ]
        rows.append(out)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ATENA_HEADERS)
    w.writerows(rows)
    return buf.getvalue()

# ====== UI（Jinja文字列） ======
INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>Eight → 宛名職人 変換 ({{version}})</title>
  <style>
    body { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, "Noto Sans JP", sans-serif; padding: 24px; }
    .card { max-width: 760px; margin: 0 auto; padding: 24px; border: 1px solid #ddd; border-radius: 12px; }
    h1 { font-size: 20px; margin-top: 0; }
    input[type=file] { margin: 12px 0; }
    button { padding: 10px 16px; border: 0; border-radius: 8px; background: #0b6; color: #fff; font-weight: 600; cursor: pointer; }
    button.secondary { background: #444; }
    .muted { color: #666; font-size: 12px; }
    .ver { font-size: 12px; color: #444; }
    .row { display:flex; gap:12px; align-items:center; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Eight → 宛名職人 変換 <span class="ver">({{version}})</span></h1>
    <form method="post" action="/convert" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv" required />
      <div class="muted">UTF-8 / カンマ区切りの Eight CSV を選択してください。</div>
      <div class="row">
        <button type="submit">変換してダウンロード</button>
        <button type="button" class="secondary" onclick="reloadDict()">建物語辞書を再読込</button>
        <button type="button" class="secondary" onclick="showVersion()">バージョン情報</button>
      </div>
    </form>
  </div>
  <script>
    async function reloadDict() {
      try {
        const res = await fetch('/reload-bldg', {method:'POST'});
        const j = await res.json();
        alert('再読込: ' + (j.ok ? '成功' : '失敗') + '\\n語数: ' + (j.count ?? '-') + '\\n更新時刻: ' + (j.reloaded_at ?? '-'));
      } catch (e) {
        alert('再読込に失敗しました: ' + e);
      }
    }
    async function showVersion() {
      const res = await fetch('/version');
      const j = await res.json();
      alert('App: ' + j.version + '\\nStarted: ' + j.started_at + '\\nBLDG words: ' + j.bldg.count + ' (last loaded: ' + j.bldg.last_loaded + ')\\nFurigana enabled: ' + j.furigana.enabled);
    }
  </script>
</body>
</html>
"""

# ====== ルーティング ======
@app.before_request
def _start_timer():
    g._t0 = time.perf_counter()

@app.after_request
def _log_response(resp):
    try:
        dt = (time.perf_counter() - getattr(g, "_t0", time.perf_counter())) * 1000.0
        logger.info("req method=%s path=%s status=%s dur_ms=%.1f len=%s",
                    request.method, request.path, resp.status_code,
                    dt, resp.calculate_content_length())
    except Exception:
        pass
    return resp

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
        logger.exception("convert failed")
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

@app.route("/reload-bldg", methods=["POST"])
def reload_bldg():
    load_bldg_words()
    return jsonify({
        "ok": True,
        "count": len(get_bldg_words()),
        "reloaded_at": app.config.get("BLDG_LAST_LOADED")
    })

@app.route("/version")
def version():
    return jsonify({
        "version": VERSION,
        "started_at": APP_STARTED_AT,
        "bldg": {
            "count": len(get_bldg_words()),
            "last_loaded": app.config.get("BLDG_LAST_LOADED")
        },
        "furigana": {
            "enabled": os.environ.get("FURIGANA_ENABLED", "1") == "1"
        }
    })

@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    # ローカル実行用（本番は gunicorn 推奨）
    app.run(host="0.0.0.0", port=8000, debug=False)
