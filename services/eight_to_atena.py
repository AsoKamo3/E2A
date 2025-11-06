# services/eight_to_atena.py　
# Eight CSV/TSV → 宛名職人CSV 変換本体（I/Oと行マッピング）
# - 列の並びは ATENA_HEADERS と厳密一致（61列）
# - 部署名の 2 分割（utils.textnorm.split_department）
# - 住所分割は converters.address.split_address を使用
# - ふりがな推定は utils.kana.to_katakana_guess（存在すれば利用）＋カタカナ強制
# - 会社名かなは 法人格除去→分割（／ 等）→上書き辞書→推測→カタカナ強制
# - 電話番号は utils.textnorm.normalize_phone で正規化し、';' 連結
#
# v2.29 : ImportError 回避（normalize_phone を utils.textnorm 側に実装前提）
#         BOM/余白除去・CSV/TSV自動判定・かなカタカナ強制・会社名オーバーライド適用

from __future__ import annotations

import io
import csv
import json
import re
from typing import List, Tuple

from converters.address import split_address
from utils.textnorm import (
    to_zenkaku,
    normalize_postcode,
    normalize_phone,
    split_department,
    strip_corp_terms,
)
from utils.kana import to_katakana_guess

__version__ = "v2.29"

# 宛名職人ヘッダ（61列：この順で出力）
ATENA_HEADERS: List[str] = [
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

# Eight 側の固定カラム（この順に存在する想定）
EIGHT_FIXED = [
    "会社名","部署名","役職","姓","名","e-mail","郵便番号","住所","TEL会社",
    "TEL部門","TEL直通","Fax","携帯電話","URL","名刺交換日"
]

# 区切り推定
def _detect_delimiter(text: str) -> str:
    head = text.splitlines()[0] if text else ""
    if "\t" in head:
        return "\t"
    return ","

# 先頭BOM/余白除去ヘッダ名
def _clean_fieldnames(fieldnames: List[str]) -> List[str]:
    cleaned = []
    for i, h in enumerate(fieldnames or []):
        h = h.strip().lstrip("\ufeff").rstrip()
        cleaned.append(h)
    return cleaned

# JSON 読み込み（存在しなければフェイルセーフ）
def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# 会社名かな 上書き辞書（data/company_kana_overrides.json）
_OVR = _load_json("data/company_kana_overrides.json")
_OVR_MAP = _OVR.get("overrides", {}) if isinstance(_OVR, dict) else {}
_OVR_VERSION = _OVR.get("version") if isinstance(_OVR, dict) else None

# 法人格リスト（data/corp_terms.json）
_CORP = _load_json("data/corp_terms.json")
_CORP_TERMS = _CORP.get("terms", []) if isinstance(_CORP, dict) else []
_CORP_VERSION = _CORP.get("version") if isinstance(_CORP, dict) else None

# 会社名かなの推定（セグメント単位）
def _company_kana_segment(seg: str) -> str:
    if not seg:
        return ""
    # 上書き辞書優先（キーは NFKC 正規化・前後空白除去で比較）
    key = seg.strip()
    if key in _OVR_MAP:
        return _OVR_MAP[key]

    # fallback: 推測 → カタカナ強制
    return to_katakana_guess(seg)  # utils.kana 側でカタカナ化フォース

def _company_kana_guess(company_name: str) -> str:
    """
    会社名かなの推定。
    1) 法人格を除去（strip_corp_terms）
    2) '／' '/' '・' '，' '、' などで分割して各セグメントを個別に変換
    3) セパレータは元の文字を維持
    """
    base = company_name or ""
    if not base:
        return ""
    # セパレータで分割し、セパレータを保持
    parts: List[str] = []
    i = 0
    # 正規表現でセパレータ or 非セパレータの交互キャプチャ
    for m in re.finditer(r"(／|/|・|，|、)", base):
        token = base[i:m.start()]
        sep = base[m.start():m.end()]
        parts.append(token)
        parts.append(sep)
        i = m.end()
    parts.append(base[i:])

    # 各非セパレータ部分に処理
    out = []
    for p in parts:
        if p in ("／","/","・","，","、"):
            out.append(p)
        else:
            stripped = strip_corp_terms(p, extra_terms=_CORP_TERMS)
            out.append(_company_kana_segment(stripped))

    return "".join(out)

def _iter_extra_flags(fieldnames: List[str], row: dict) -> List[str]:
    """Eight 固定カラム以降で値が '1' のヘッダ名を収集。"""
    flags = []
    tail_headers = fieldnames[len(EIGHT_FIXED):] if fieldnames else []
    for hdr in tail_headers:
        val = (row.get(hdr, "") or "").strip()
        if val == "1":
            flags.append(hdr)
    return flags

def convert_eight_csv_text_to_atena_csv_text(text: str) -> str:
    """
    Eight CSV/TSV（UTF-8, 1行目ヘッダ）→ 宛名職人 CSV テキスト
    - 出力には ATENA_HEADERS（61列）を必ず含む
    """
    # 区切り自動検出
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    # ヘッダ名のBOM/余白除去
    reader.fieldnames = _clean_fieldnames(reader.fieldnames or [])
    rows_out: List[List[str]] = []

    for row in reader:
        g = lambda k: (row.get(k, "") or "").strip()

        # --- 入力の取得 ---
        company_raw = g("会社名")
        company     = to_zenkaku(company_raw)  # 表示値は全角化
