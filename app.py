# app.py
# Eight → 宛名職人 変換 最小版 v1.6
# 単一ファイル。POST /convert で直接 CSV を返します。

import io
import csv
import re
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort

from services.eight_to_atena import (
    convert_eight_csv_text_to_atena_csv_text,
    __version__ as CONVERTER_VERSION,
)
from utils.textnorm import load_bldg_words  # 建物語辞書を起動時にロード

VERSION = "v1.6"

# 起動時に辞書ロード（data/bldg_words.json が無い場合はデフォルトにフォールバック）
load_bldg_words("data/bldg_words.json")

# ====== Web: 超簡易UI（Jinja文字列） ======
INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>Eight → 宛名職人 変換 ({{version}} / converter {{converter}})</title>
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
    <h1>Eight → 宛名職人 変換 <span class="ver">({{version}} / converter {{converter}})</span></h1>
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
    return render_template_string(INDEX_HTML, version=VERSION, converter=CONVERTER_VERSION)

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
