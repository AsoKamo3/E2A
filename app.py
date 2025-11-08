# app.py
# Eight → 宛名職人 変換 v1.22
# - トップページと /healthz に app / converter / address / textnorm / kana / 各辞書のバージョンを表示
# - 会社名かな辞書（JP/EN）・人名辞書（フル/姓/名）・エリア局番のバージョン表示
# - /selftest/overrides, /selftest/company_kana の簡易自己診断API（v1.21）を堅牢化
#   * services 側の戻り値/関数シグネチャ変更（v2.37+）にも両対応

import io
import os
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, abort, jsonify

from services.eight_to_atena import (
    convert_eight_csv_text_to_atena_csv_text,
    __version__ as CONVERTER_VERSION,
    get_company_override_versions,
    get_person_dict_versions,
    get_area_codes_version,
    # selftest 用（内部関数）
    _load_company_overrides,
    _company_kana,
    _read_json_version,
)
from utils.textnorm import to_zenkaku_wide

VERSION = "v1.22"

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
            company_overrides_version,
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

# --- Selftest: 辞書のロード状況/設定確認（旧/新形式に両対応） ---
@app.route("/selftest/overrides")
def selftest_overrides():
    try:
        loaded = _load_company_overrides()
    except Exception as e:
        return jsonify(dict(ok=False, error=f"_load_company_overrides failed: {e!r}")), 500

    # 旧: 4要素 / 新: 8要素（v2.37+）
    jp_idx = en_idx = jp_cfg = en_cfg = None
    tok_jp = tok_en = None
    min_len = None
    charwise = None

    if isinstance(loaded, (list, tuple)):
        if len(loaded) >= 4:
            jp_idx, en_idx, jp_cfg, en_cfg = loaded[:4]
        if len(loaded) >= 6:
            tok_jp, tok_en = loaded[4:6]
        if len(loaded) >= 8:
            min_len, charwise = loaded[6:8]

    # バージョン（トークン辞書も）
    jp_ver, en_ver = get_company_override_versions()
    jp_tok_ver = _read_json_version(os.path.join("data", "company_overrides_tokens_jp.json"))
    en_tok_ver = _read_json_version(os.path.join("data", "company_overrides_tokens_en.json"))

    return jsonify(dict(
        ok=True,
        sizes=dict(
            jp=len(jp_idx or {}),
            en=len(en_idx or {}),
            tokens_jp=len(tok_jp or {}),
            tokens_en=len(tok_en or {}),
        ),
        versions=dict(
            company_overrides_jp=jp_ver,
            company_overrides_en=en_ver,
            company_overrides_tokens_jp=jp_tok_ver,
            company_overrides_tokens_en=en_tok_ver,
        ),
        normalize=dict(jp=jp_cfg, en=en_cfg),
        tokens_present=dict(jp=bool(tok_jp), en=bool(tok_en)),
        env=dict(
            COMPANY_PARTIAL_OVERRIDES=os.environ.get("COMPANY_PARTIAL_OVERRIDES"),
            COMPANY_PARTIAL_TOKEN_MIN_LEN=os.environ.get("COMPANY_PARTIAL_TOKEN_MIN_LEN"),
            PARTIAL_ACRONYM_CHARWISE=os.environ.get("PARTIAL_ACRONYM_CHARWISE"),
        ),
    )), 200

# --- Selftest: 会社名かな の単発確認（旧/新シグネチャに両対応） ---
@app.route("/selftest/company_kana")
def selftest_company_kana():
    name = request.args.get("name", "")
    try:
        loaded = _load_company_overrides()
    except Exception as e:
        return jsonify(dict(ok=False, error=f"_load_company_overrides failed: {e!r}")), 500

    # 共通：入力は画面同様に全角ワイド化してから渡す
    normalized_name = to_zenkaku_wide(name)

    # アンパック（4 or 8）
    jp_idx = en_idx = jp_cfg = en_cfg = None
    tok_jp = tok_en = None
    min_len = None
    charwise = None
    if isinstance(loaded, (list, tuple)):
        if len(loaded) >= 4:
            jp_idx, en_idx, jp_cfg, en_cfg = loaded[:4]
        if len(loaded) >= 6:
            tok_jp, tok_en = loaded[4:6]
        if len(loaded) >= 8:
            min_len, charwise = loaded[6:8]

    # 旧/新シグネチャ両対応で呼び出し
    try:
        kana = _company_kana(normalized_name, jp_idx, en_idx, jp_cfg, en_cfg)
    except TypeError:
        # 新（v2.37+）: 追加引数あり
        kana = _company_kana(normalized_name, jp_idx, en_idx, jp_cfg, en_cfg, tok_jp, tok_en, min_len, charwise)
    except Exception as e:
        return jsonify(dict(ok=False, error=f"_company_kana failed: {e!r}")), 500

    return jsonify(dict(
        ok=True,
        input=name,
        normalized=normalized_name,
        kana=kana,
    )), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", "8000")), debug=False)
