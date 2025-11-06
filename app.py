# app.py
# Eight → 宛名職人 変換 v1.10 (UIに各モジュールのバージョン表示)
# - トップページに app / converter / address / textnorm の版を表示
# - /healthz も同じ情報をJSONで返却
# - 変換は services.eight_to_atena (v2.19) を利用（CSV/TSV自動判定OK）

import io
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort, jsonify

from services.eight_to_atena import (
    convert_eight_csv_text_to_atena_csv_text,
    __version__ as CONVERTER_VERSION,
)

VERSION = "v1.10"

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
    .muted { color: #666; font-size: 12px; }
    .verbox { background: #f7f7f7; border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin: 12px 0 0; }
    .verbox code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Eight → 宛名職人 変換</h1>
    <form method="post" action="/convert" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" required />
      <div class="muted">UTF-8 の Eightエクスポート（CSV/TSV）を選択してください。区切りは自動判定します。</div>
      <p><button type="submit">変換してダウンロード</button></p>
    </form>
    <div class="verbox">
      <div><strong>App:</strong> <code>{{version}}</code></div>
      <div><strong>Converter:</strong> <code>{{conv}}</code></div>
      <div><strong>Address:</strong> <code>{{addr_ver if addr_ver else "N/A"}}</code></div>
      <div><strong>Textnorm:</strong> <code>{{txn_ver if txn_ver else "N/A"}}</code></div>
    </div>
    <div class="muted" style="margin-top:8px;">※ 上記は現在稼働中のモジュールのバージョンです。</div>
  </div>
</body>
</html>
"""

app = Flask(__name__)

def _module_versions():
    """各モジュールのバージョンを安全に取得"""
    try:
        from converters.address import __version__ as ADDR_VER
    except Exception:
        ADDR_VER = None
    try:
        from utils.textnorm import __version__ as TXN_VER
    except Exception:
        TXN_VER = None
    return ADDR_VER, TXN_VER

@app.route("/", methods=["GET"])
def index():
    addr_ver, txn_ver = _module_versions()
    return render_template_string(
        INDEX_HTML,
        version=VERSION,
        conv=CONVERTER_VERSION,
        addr_ver=addr_ver,
        txn_ver=txn_ver,
    )

@app.route("/convert", methods=["POST"])
def convert():
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        abort(400, "CSV/TSVファイルが選択されていません。")

    # Eight標準はUTF-8想定。BOM/余白・区切り判定は変換関数側で吸収。
    try:
        csv_or_tsv_text = f.stream.read().decode("utf-8")
    except UnicodeDecodeError:
        abort(400, "文字コードは UTF-8 にしてください。")

    try:
        out_csv_text = convert_eight_csv_text_to_atena_csv_text(csv_or_tsv_text)
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
    addr_ver, txn_ver = _module_versions()
    return jsonify(
        ok=True,
        app=VERSION,
        converter=CONVERTER_VERSION,
        address=addr_ver,
        textnorm=txn_ver,
    ), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
