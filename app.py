# app.py
# Eight → 宛名職人 変換（UI + HTTP I/O だけ）
# 役割: アップロードされた Eight CSV を受け取り、変換結果 CSV を返す
# 依存: eight_to_atena.convert_eight_csv_text_to_atena_csv_text（下の薄いラッパーモジュール）

import io
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort

# ルートの eight_to_atena.py（互換ラッパー）から関数とバージョンを取得
from eight_to_atena import convert_eight_csv_text_to_atena_csv_text, __version__ as CONVERTER_VERSION

APP_VERSION = "v1.5"  # アプリ（UI側）のバージョン

# ---- シンプルなワンページUI（テンプレート） ----
INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>Eight → 宛名職人 変換 (App {{app_ver}} / Conv {{conv_ver}})</title>
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
    <h1>Eight → 宛名職人 変換 <span class="ver">(App {{app_ver}} / Conv {{conv_ver}})</span></h1>
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
    return render_template_string(INDEX_HTML, app_ver=APP_VERSION, conv_ver=CONVERTER_VERSION)

@app.route("/convert", methods=["POST"])
def convert():
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        abort(400, "CSVファイルが選択されていません。")

    try:
        # Eight の CSV は UTF-8 前提
        csv_text = f.stream.read().decode("utf-8")
    except UnicodeDecodeError:
        abort(400, "文字コードは UTF-8 にしてください。")

    try:
        # コアの変換関数（services/eight_to_atena.py の実体）に丸投げ
        out_csv_text = convert_eight_csv_text_to_atena_csv_text(csv_text)
    except Exception as e:
        # 変換エラーは 500 で見せる（詳細はログ等で確認）
        abort(500, f"変換に失敗しました: {e}")

    # ダウンロードとして返す
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
    # Render/Gunicorn 本番では使われないが、ローカル確認用
    app.run(host="0.0.0.0", port=8000, debug=False)
