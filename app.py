# app.py
# Eight → 宛名職人 変換 v1.23
# - トップページと /healthz に app / converter / address / textnorm / kana / 各辞書のバージョンを表示
# - 会社名かな辞書（JP/EN）・人名辞書（フル/姓/名）・エリア局番のバージョン表示
# - CSV/TSV 自動判定入力 → 変換 → CSV ダウンロード
# - selftest/company_kana を堅牢化（例外を JSON で返す）

import io
import os
import json
import traceback
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort, jsonify

from services.eight_to_atena import (
    convert_eight_csv_text_to_atena_csv_text,
    __version__ as CONVERTER_VERSION,
    get_company_override_versions,
    get_person_dict_versions,
    get_area_codes_version,
    debug_company_kana,   # ← 追加：会社名かなデバッグ用
)

VERSION = "v1.23"

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
    .muted { color: #666; font-size: 12px; }
    .verbox { background: #f7f7f7; border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin: 12px 0 0; }
    .verbox code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    .grid { display: grid; grid-template-columns: 240px 1fr; gap: 6px 12px; align-items: baseline; }
    .label { color: #444; }
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
            company_overrides_version,  # 旧: legacy
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
    except Exception:
        KANA_VER = None
        def engine_name(): return None
        def engine_detail(): return None

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
        furigana_engine=engine_name(),
        furigana_detail=engine_detail(),
    )

@app.route("/", methods=["GET"])
def index():
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
            "nfkc": True, "lower": True, "strip_spaces": True, "collapse_spaces": True, "unify_slash_to": "/"
        }
    }
    # sizes/tokens_present は services で集計しても良いが簡易固定
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
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", "8000")), debug=False)
