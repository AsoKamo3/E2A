# app.py
# Eight → 宛名職人 変換 v1.4.0
# - トップページと /healthz に app / converter / address / textnorm / kana / 各辞書のバージョンを表示
# - 会社名かな辞書（JP/EN）・人名辞書（フル/姓/名）・エリア局番のバージョン表示
# - CSV/TSV 自動判定入力 → 変換 → CSV ダウンロード
# - selftest/company_kana を堅牢化（例外を JSON で返す）
# - v1.3.0: HEAD / に対応
# - v1.4.0: 人名かな確認用フロー /convert_review + /download_reviewed を追加
#            （変換ロジック本体は変更しない）

import io
import os
import json
import csv
import traceback
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort, jsonify

from services.eight_to_atena import (
    convert_eight_csv_text_to_atena_csv_text,
    __version__ as CONVERTER_VERSION,
    get_company_override_versions,
    get_person_dict_versions,
    get_area_codes_version,
    debug_company_kana,
)

VERSION = "v1.4.0"

INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>Eight → 宛名職人 変換 ({{version}})</title>
  <style>
    body { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, "Noto Sans JP", sans-serif; padding: 24px; }
    .card { max-width: 880px; margin: 0 auto; padding: 24px; border: 1px solid #ddd; border-radius: 12px; }
    h1 { font-size: 20px; margin-top: 0; }
    input[type=file] { margin: 12px 0; }
    button { padding: 10px 16px; border: 0; border-radius: 8px; background: #0b6; color: #fff; font-weight: 600; cursor: pointer; }
    button.secondary { background: #06c; }
    .muted { color: #666; font-size: 12px; }
    .verbox { background: #f7f7f7; border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin: 12px 0 0; }
    .verbox code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    .grid { display: grid; grid-template-columns: 240px 1fr; gap: 6px 12px; align-items: baseline; }
    .label { color: #444; }
    form { margin-bottom: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Eight → 宛名職人 変換</h1>

    <!-- 従来フロー：即ダウンロード -->
    <form method="post" action="/convert" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" required />
      <div class="muted">UTF-8 の Eightエクスポート（CSV/TSV）を選択してください。区切りは自動判定します。</div>
      <p><button type="submit">そのまま変換してダウンロード</button></p>
    </form>

    <!-- 新フロー：人名かな確認後にダウンロード -->
    <form method="post" action="/convert_review" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" required />
      <div class="muted">
        姓 / 名 / 姓かな / 名かな をブラウザ上で確認・修正してから、最終CSVをダウンロードできます。
      </div>
      <p><button type="submit" class="secondary">人名かなを確認してからダウンロード</button></p>
    </form>

    <div class="verbox">
      <div class="grid">
        <div class="label"><strong>App</strong></div><div><code>{{version}}</code></div>
        <div class="label"><strong>Converter</strong></div><div><code>{{conv}}</code></div>
        <div class="label">Address</div><div><code>{{addr_ver or "N/A"}}</code></div>
        <div class="label">Textnorm</div><div><code>{{txn_ver or "N/A"}}</code></div>
        <div class="label">Kana</div><div><code>{{kana_ver or "N/A"}}</code></div>
        <div class="label">Area Codes</div><div><code>{{area_codes_ver or "N/A"}}</code></div>

        <div class="label">Building Dict</div><div><code>{{bldg_dict_ver or "N/A"}}</code></div>
        <div class="label">Corp Terms</div><div><code>{{corp_terms_ver or "N/A"}}</code></div>

        <div class="label">Company Overrides (JP)</div><div><code>{{company_ovr_jp or "N/A"}}</code></div>
        <div class="label">Company Overrides (EN)</div><div><code>{{company_ovr_en or "N/A"}}</code></div>

        <div class="label">Person Full Overrides</div><div><code>{{person_full_ver or "N/A"}}</code></div>
        <div class="label">Surname Terms</div><div><code>{{surname_terms_ver or "N/A"}}</code></div>
        <div class="label">Given Terms</div><div><code>{{given_terms_ver or "N/A"}}</code></div>

        <div class="label">Company Overrides (legacy)</div><div><code>{{company_overrides_ver or "—"}}</code></div>
      </div>
      <div class="muted" style="margin-top:8px;">※ 上記は現在稼働中のモジュール/辞書のバージョンです。</div>
    </div>
  </div>
</body>
</html>
"""

REVIEW_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>人名かな確認 - Eight → 宛名職人</title>
  <style>
    body { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, "Noto Sans JP", sans-serif; padding: 24px; }
    .card { max-width: 1100px; margin: 0 auto; padding: 24px; border: 1px solid #ddd; border-radius: 12px; }
    h1 { font-size: 20px; margin-top: 0; }
    table { border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 12px; }
    th, td { border: 1px solid #ddd; padding: 4px 6px; vertical-align: top; }
    th { background: #f5f5f5; position: sticky; top: 0; z-index: 1; }
    input[type="text"] { width: 100%; box-sizing: border-box; padding: 2px 4px; font-size: 12px; }
    .muted { color: #666; font-size: 12px; margin-top: 4px; }
    .btn-row { margin-top: 12px; display: flex; gap: 8px; align-items: center; }
    button { padding: 8px 14px; border: 0; border-radius: 6px; background: #0b6; color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
    button.secondary { background: #999; }
    .scroll-wrap { max-height: 520px; overflow: auto; margin-top: 8px; border: 1px solid #eee; border-radius: 8px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>人名かな確認</h1>
    <div class="muted">
      姓 / 名 / 姓かな / 名かな を必要に応じて修正してください。<br>
      「この内容でCSVをダウンロード」を押すと、下記の表から宛名職人用CSVを生成します。
    </div>

    <form id="review-form" method="post" action="/download_reviewed">
      <div class="scroll-wrap">
        <table>
          <thead>
            <tr>
              {% for h in headers %}
              <th>{{ h }}</th>
              {% endfor %}
            </tr>
          </thead>
          <tbody>
            {% for row in rows %}
            <tr>
              {% for cell in row %}
                {% if loop.index0 == idx_last or loop.index0 == idx_first or loop.index0 == idx_last_k or loop.index0 == idx_first_k %}
                  <td><input type="text" value="{{ cell|e }}" data-col="{{ loop.index0 }}"></td>
                {% else %}
                  <td data-col="{{ loop.index0 }}" data-value="{{ cell|e }}">{{ cell }}</td>
                {% endif %}
              {% endfor %}
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <div class="btn-row">
        <button type="submit">この内容でCSVをダウンロード</button>
        <a href="/" class="muted" style="text-decoration:none;">← 最初の画面に戻る</a>
      </div>

      <input type="hidden" name="csv" id="csv-input">
    </form>
  </div>

  {% raw %}
  <script>
  (function() {
    function toCsvValue(v) {
      if (v == null) return "";
      v = String(v);
      if (v.indexOf('"') !== -1 || v.indexOf(",") !== -1 || v.indexOf("\n") !== -1 || v.indexOf("\r") !== -1) {
        v = '"' + v.replace(/"/g, '""') + '"';
      }
      return v;
    }

    var form = document.getElementById("review-form");
    form.addEventListener("submit", function() {
      var rows = [];
      // ヘッダ行
      var headers = [];
      var ths = document.querySelectorAll("thead th");
      for (var i = 0; i < ths.length; i++) {
        headers.push(ths[i].textContent || "");
      }
      rows.push(headers);

      // データ行
      var trs = document.querySelectorAll("tbody tr");
      for (var r = 0; r < trs.length; r++) {
        var tds = trs[r].querySelectorAll("td");
        var cols = [];
        for (var c = 0; c < tds.length; c++) {
          var td = tds[c];
          var input = td.querySelector("input");
          var val;
          if (input) {
            val = input.value;
          } else if (td.getAttribute("data-value") !== null) {
            val = td.getAttribute("data-value");
          } else {
            val = td.textContent || "";
          }
          cols.push(toCsvValue(val));
        }
        rows.push(cols);
      }

      var csvText = rows.map(function(row) {
        return row.join(",");
      }).join("\\n");

      document.getElementById("csv-input").value = csvText;
    });
  })();
  </script>
  {% endraw %}
</body>
</html>
"""

app = Flask(__name__)

def _module_versions():
    """各モジュールと辞書のバージョンを安全に取得"""
    try:
        from converters.address import __version__ as ADDR_VER
    except Exception:
        ADDR_VER = None

    try:
        from utils.textnorm import (
            __version__ as TXN_VER,
            bldg_words_version,
            corp_terms_version,
            company_overrides_version,  # legacy
        )
        BLDG_VER = bldg_words_version()
        CORP_TERMS_VER = corp_terms_version()
        COMPANY_OVR_LEGACY = company_overrides_version()
    except Exception:
        TXN_VER = None
        BLDG_VER = None
        CORP_TERMS_VER = None
        COMPANY_OVR_LEGACY = None

    try:
        from utils.kana import __version__ as KANA_VER, engine_name, engine_detail
        KANA_NAME = engine_name()
        KANA_DETAIL = engine_detail()
    except Exception:
        KANA_VER = None
        KANA_NAME = None
        KANA_DETAIL = None

    try:
        comp_jp, comp_en = get_company_override_versions()
    except Exception:
        comp_jp, comp_en = None, None

    try:
        p_full, p_surname, p_given = get_person_dict_versions()
    except Exception:
        p_full, p_surname, p_given = None, None, None

    try:
        area_codes_ver = get_area_codes_version()
    except Exception:
        area_codes_ver = None

    return dict(
        address=ADDR_VER,
        textnorm=TXN_VER,
        kana=KANA_VER,
        bldg_dict=BLDG_VER,
        corp_terms=CORP_TERMS_VER,
        company_overrides_legacy=COMPANY_OVR_LEGACY,
        company_overrides_jp=comp_jp,
        company_overrides_en=comp_en,
        person_full=p_full,
        surname_terms=p_surname,
        given_terms=p_given,
        area_codes=area_codes_ver,
        furigana_engine=KANA_NAME,
        furigana_detail=KANA_DETAIL,
    )

@app.route("/", methods=["GET", "HEAD"])
def index():
    # Render のヘルスチェック対策：HEAD は中身なしで 200
    if request.method == "HEAD":
        return ("", 200)
    v = _module_versions()
    return render_template_string(
        INDEX_HTML,
        version=VERSION,
        conv=CONVERTER_VERSION,
        addr_ver=v["address"],
        txn_ver=v["textnorm"],
        kana_ver=v["kana"],
        area_codes_ver=v["area_codes"],
        bldg_dict_ver=v["bldg_dict"],
        corp_terms_ver=v["corp_terms"],
        company_overrides_ver=v["company_overrides_legacy"],
        company_ovr_jp=v["company_overrides_jp"],
        company_ovr_en=v["company_overrides_en"],
        person_full_ver=v["person_full"],
        surname_terms_ver=v["surname_terms"],
        given_terms_ver=v["given_terms"],
    )

@app.route("/convert", methods=["POST"])
def convert():
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        abort(400, "CSV/TSVファイルが選択されていません。")

    try:
        text = f.stream.read().decode("utf-8")
    except UnicodeDecodeError:
        abort(400, "文字コードは UTF-8 にしてください。")

    try:
        out_csv_text = convert_eight_csv_text_to_atena_csv_text(text)
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

# 新フロー：人名かな確認用
@app.route("/convert_review", methods=["POST"])
def convert_review():
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        abort(400, "CSV/TSVファイルが選択されていません。")

    try:
        text = f.stream.read().decode("utf-8")
    except UnicodeDecodeError:
        abort(400, "文字コードは UTF-8 にしてください。")

    try:
        converted = convert_eight_csv_text_to_atena_csv_text(text)
    except Exception as e:
        abort(500, f"変換に失敗しました: {e}")

    buf = io.StringIO(converted)
    reader = csv.reader(buf)
    try:
        headers = next(reader)
    except StopIteration:
        abort(400, "変換結果が空でした。")

    rows = list(reader)

    # 必須列のインデックスを確認
    try:
        idx_last = headers.index("姓")
        idx_first = headers.index("名")
        idx_last_k = headers.index("姓かな")
        idx_first_k = headers.index("名かな")
    except ValueError:
        abort(500, "変換結果に必要な列（姓/名/姓かな/名かな）が存在しません。")

    return render_template_string(
        REVIEW_HTML,
        headers=headers,
        rows=rows,
        idx_last=idx_last,
        idx_first=idx_first,
        idx_last_k=idx_last_k,
        idx_first_k=idx_first_k,
    )

@app.route("/download_reviewed", methods=["POST"])
def download_reviewed():
    csv_text = request.form.get("csv", "")
    if not csv_text:
        abort(400, "CSVデータが送信されていません。")

    buf = io.BytesIO(csv_text.encode("utf-8"))
    filename = f"atena_reviewed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
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
    v = _module_versions()
    info = dict(
        ok=True,
        app=VERSION,
        converter=CONVERTER_VERSION,
        address=v["address"],
        textnorm=v["textnorm"],
        kana=v["kana"],
        area_codes=v["area_codes"],
        building_dict=v["bldg_dict"],
        corp_terms=v["corp_terms"],
        company_overrides_legacy=v["company_overrides_legacy"],
        company_overrides_jp=v["company_overrides_jp"],
        company_overrides_en=v["company_overrides_en"],
        person_full=v["person_full"],
        surname_terms=v["surname_terms"],
        given_terms=v["given_terms"],
        furigana_engine=v["furigana_engine"],
        furigana_detail=v["furigana_detail"],
        python=f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
        env_FURIGANA_ENABLED=os.environ.get("FURIGANA_ENABLED"),
        executable=os.path.join(
            os.environ.get("VIRTUAL_ENV") or os.path.dirname(os.sys.executable),
            "bin",
            f"python{os.sys.version_info.major}.{os.sys.version_info.minor}"
        ) if os.environ.get("VIRTUAL_ENV") else os.sys.executable,
        sys_path=list(os.sys.path),
    )
    return jsonify(info), 200

# ---- Selftest routes (robust) ----
@app.route("/selftest/overrides", methods=["GET"])
def selftest_overrides():
    try:
        jp, en = get_company_override_versions()
    except Exception:
        jp, en = None, None
    env_info = {
        "COMPANY_PARTIAL_OVERRIDES": os.environ.get("COMPANY_PARTIAL_OVERRIDES"),
        "COMPANY_PARTIAL_TOKEN_MIN_LEN": os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN"),
        "PARTIAL_ACRONYM_CHARWISE": os.environ.get("PARTIAL_ACRONYM_CHARWISE"),
    }
    norm = {
        "jp": {
            "nfkc": True, "strip_spaces": True, "collapse_spaces": True,
            "unify_middle_dot": True, "unify_slash_to": "／", "fullwidth_ascii": True
        },
        "en": {
            "nfkc": True, "lower": True, "strip_spaces": True,
            "collapse_spaces": True, "unify_slash_to": "/"
        }
    }
    payload = dict(
        ok=True,
        versions={
            "company_overrides_jp": jp,
            "company_overrides_en": en,
            "company_overrides_tokens_jp": None,
            "company_overrides_tokens_en": None,
        },
        normalize=norm,
        env=env_info,
        # 固定値（目安）。実値が欲しければ services 側で返す実装に変更。
        sizes={"jp": 2, "en": 1, "tokens_jp": 14, "tokens_en": 40},
        tokens_present={"jp": True, "en": True},
    )
    return jsonify(payload), 200

@app.route("/selftest/company_kana", methods=["GET"])
def selftest_company_kana():
    name = request.args.get("name", "")
    try:
        info = debug_company_kana(name)
        info["ok"] = True
        return jsonify(info), 200
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({
            "ok": False,
            "error": str(e),
            "traceback": tb,
            "input": name
        }), 500

if __name__ == "__main__":
    # Render 用: PORT が指定される前提だが、ローカル用にデフォルト 8000
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
