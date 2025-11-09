# app.py
# Minimal Flask app with light /healthz, detailed /healthz, and selftests
# v1.3.0

from __future__ import annotations

import os
import json
from typing import Any, Dict, Tuple

from flask import Flask, request, jsonify, Response

from services.eight_to_atena import (
    __version__ as CONVERTER_VERSION,
    convert_eight_csv_text_to_atena_csv_text,
    get_company_override_versions,
    get_person_dict_versions,
    get_area_codes_version,
    debug_company_kana,
)

APP_VERSION = "v1.3.0"

app = Flask(__name__)

def _bool_env(name: str) -> bool:
    v = os.getenv(name, "")
    return v not in ("", "0", "false", "False", "no", "NO")

@app.get("/healthz")
def healthz() -> Response:
    """軽量/詳細の2モード。Renderのヘルスチェックはlight推奨: /healthz?light=1"""
    light = request.args.get("light") in ("1", "true", "True") or _bool_env("HEALTHZ_LIGHT")
    if light:
        data = {
            "ok": True,
            "app": APP_VERSION,
            "converter": CONVERTER_VERSION,
        }
        return jsonify(data), 200

    # 詳細版（起動直後は少し重いので、light をヘルスチェックに使うことを推奨）
    jp_ver, en_ver = get_company_override_versions()
    full_ver, surname_ver, given_ver = get_person_dict_versions()
    area_ver = get_area_codes_version()

    furigana_engine = "pykakasi"
    furigana_detail = []
    try:
        import pykakasi  # noqa: F401
        furigana_detail = ["pykakasi", "pykakasi ok"]
    except Exception as e:
        furigana_detail = ["pykakasi", f"error: {type(e).__name__}: {e}"]

    data = {
        "ok": True,
        "app": APP_VERSION,
        "converter": CONVERTER_VERSION,
        "company_overrides_jp": jp_ver,
        "company_overrides_en": en_ver,
        "person_full": full_ver,
        "surname_terms": surname_ver,
        "given_terms": given_ver,
        "area_codes": area_ver,
        "furigana_engine": furigana_engine,
        "furigana_detail": furigana_detail,
        "env_FURIGANA_ENABLED": os.getenv("FURIGANA_ENABLED", "1"),
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
        "sys_path": list(os.sys.path),
        "executable": os.sys.executable,
    }
    return jsonify(data), 200

@app.get("/selftest/overrides")
def selftest_overrides() -> Response:
    """
    会社辞書の正規化設定やサイズ、ENV などを確認（UI/運用のデバッグ用）。
    ※ 重い処理はしない
    """
    # ファイルを直接読む（軽量）
    def _load_json(path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    jp = _load_json(os.path.join("data", "company_kana_overrides_jp.json"))
    en = _load_json(os.path.join("data", "company_kana_overrides_en.json"))

    def _size_info(obj: Dict[str, Any]) -> Tuple[int, int, bool, bool]:
        ov = obj.get("overrides") or {}
        tk = obj.get("tokens") or {}
        return len(ov), len(tk), bool(ov), bool(tk)

    jp_ov_sz, jp_tk_sz, jp_ov_ok, jp_tk_ok = _size_info(jp)
    en_ov_sz, en_tk_sz, en_ov_ok, en_tk_ok = _size_info(en)

    data = {
        "ok": True,
        "env": {
            "COMPANY_PARTIAL_OVERRIDES": os.getenv("COMPANY_PARTIAL_OVERRIDES", ""),
            "COMPANY_PARTIAL_TOKEN_MIN_LEN": os.getenv("COMPANY_PARTIAL_TOKEN_MIN_LEN", ""),
            "PARTIAL_ACRONYM_CHARWISE": os.getenv("PARTIAL_ACRONYM_CHARWISE", ""),
            "PARTIAL_ACRONYM_MAX_LEN": os.getenv("PARTIAL_ACRONYM_MAX_LEN", ""),
        },
        "normalize": {
            "jp": jp.get("normalize"),
            "en": en.get("normalize"),
        },
        "sizes": {
            "jp_overrides": jp_ov_sz,
            "jp_tokens": jp_tk_sz,
            "en_overrides": en_ov_sz,
            "en_tokens": en_tk_sz,
        },
        "tokens_present": {
            "jp": jp_tk_ok,
            "en": en_tk_ok,
        },
        "versions": {
            "company_overrides_jp": jp.get("version"),
            "company_overrides_en": en.get("version"),
            "company_overrides_tokens_jp": None,
            "company_overrides_tokens_en": None,
        },
    }
    return jsonify(data), 200

@app.get("/selftest/company_kana")
def selftest_company_kana() -> Response:
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    try:
        data = debug_company_kana(name)
        data["ok"] = True
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

@app.post("/convert")
def convert() -> Response:
    """
    入力: text/plain の CSV/TSV（Eight のエクスポート）
    出力: text/csv（宛名職人フォーマット）
    """
    try:
        text = request.get_data(as_text=True) or ""
        if not text.strip():
            return Response("empty input", status=400)
        out_csv = convert_eight_csv_text_to_atena_csv_text(text)
        return Response(out_csv, status=200, mimetype="text/csv; charset=utf-8")
    except Exception as e:
        return Response(f"convert error: {type(e).__name__}: {e}", status=500, mimetype="text/plain; charset=utf-8")

if __name__ == "__main__":
    # 開発用（Render では WSGI サーバが起動）
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
