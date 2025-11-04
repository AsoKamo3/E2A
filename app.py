# -*- coding: utf-8 -*-
import io
import os
import csv
from datetime import datetime
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from eight_to_atena import convert_eight_csv_to_atena_csv

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        flash("CSVファイルを選択してください。")
        return redirect(url_for("index"))

    f = request.files["file"]
    if not f or f.filename == "":
        flash("CSVファイルを選択してください。")
        return redirect(url_for("index"))

    try:
        raw = f.read()
        # 入力は UTF-8 前提（BOM あり/なし両対応）
        text = raw.decode("utf-8-sig")
    except Exception:
        flash("UTF-8 の CSV をアップロードしてください。")
        return redirect(url_for("index"))

    try:
        output_bytes = convert_eight_csv_to_atena_csv(text)
    except Exception as e:
        flash(f"変換中にエラー: {e}")
        return redirect(url_for("index"))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"atena_from_eight_{ts}.csv"

    return send_file(
        io.BytesIO(output_bytes),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
