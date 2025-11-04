# utils/textnorm.py
# 共通テキストユーティリティ（全角化・電話/郵便の正規化・部署分割・英語判定・丁目番地正規化・建物語ローダ）
# - 他モジュール（services/eight_to_atena.py, converters/address.py など）からインポートされる想定
# - 依存: 標準ライブラリのみ

from __future__ import annotations

import os
import re
import json
import logging
import unicodedata
from pathlib import Path
from typing import List, Tuple

__all__ = [
    "to_zenkaku",
    "normalize_postcode",
    "normalize_phone",
    "split_department",
    "is_english_only",
    "normalize_block_notation",
    "load_bldg_words",
]

logger = logging.getLogger(__name__)


# ============================================================
# 全角統一
# ============================================================
def to_zenkaku(s: str) -> str:
    """
    文字列を「日本語向けの見た目で揃えやすい」全角主体に正規化する。
    - ダッシュ系記号を「全角ハイフン風（－）」へ寄せる
    - 英数字/一部記号を全角に変換
    """
    if not s:
        return ""
    # 互換正規化で形を揃える
    t = unicodedata.normalize("NFKC", s)
    # ダッシュ系を横並び統一
    t = re.sub(r"[‐-‒–—―ｰ\-−]", "－", t)

    # 半角英数・一部記号 → 全角
    def _to_wide_char(ch: str) -> str:
        code = ord(ch)
        if 0x30 <= code <= 0x39:  # 0-9
            return chr(code + 0xFEE0)
        if 0x41 <= code <= 0x5A:  # A-Z
            return chr(code + 0xFEE0)
        if 0x61 <= code <= 0x7A:  # a-z
            return chr(code + 0xFEE0)
        table = {
            "/": "／",
            "#": "＃",
            "+": "＋",
            ".": "．",
            ",": "，",
            ":": "：",
            "(": "（",
            ")": "）",
            "[": "［",
            "]": "］",
            "&": "＆",
            "@": "＠",
            "~": "～",
            "_": "＿",
            "'": "’",
            '"': "”",
            "%": "％",
        }
        return table.get(ch, ch)

    return "".join(_to_wide_char(c) for c in t)


# ============================================================
# 郵便番号
# ============================================================
def normalize_postcode(s: str) -> str:
    """
    郵便番号を 7桁→ xxx-xxxx の形に整形。その他は入力をそのまま返す。
    """
    if not s:
        return ""
    z = re.sub(r"\D", "", s)
    if len(z) == 7:
        return f"{z[:3]}-{z[3:]}"
    return s


# ============================================================
# 電話番号
# ============================================================
def normalize_phone(*nums: str) -> str:
    """
    各種電話番号の簡易正規化と結合。
    - 携帯(070/080/090)は 3-4-4
    - 03/04/06 は 2-4-4（簡略）
    - それ以外は長さで分岐（NTT標準をざっくり）
    - 複数が与えられた場合は「;」で連結
    """
    cleaned: List[str] = []
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
        if d.startswith("0") and len(d) in (10, 11):
            if len(d) == 10:
                cleaned.append(f"{d[:3]}-{d[3:6]}-{d[6:]}")
            else:
                cleaned.append(f"{d[:3]}-{d[3:7]}-{d[7:]}")
            continue
        cleaned.append(n)  # 不明形式は原形を保持
    return ";".join(cleaned)


# ============================================================
# 部署の簡易 2 分割
# ============================================================
def split_department(dept: str) -> Tuple[str, str]:
    """
    部署名を「前半/後半」に大まかに分け、各要素は全角化。
    境界は > / | などの区切りを手掛かりにする。
    """
    if not dept:
        return "", ""
    parts = re.split(
        r"[\/\|]|[\s　]*>[>\s　]*",
        dept,
    )
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        return to_zenkaku(dept), ""
    k = (len(parts) + 1) // 2  # 前半に多め
    left = "　".join(to_zenkaku(p) for p in parts[:k])
    right = "　".join(to_zenkaku(p) for p in parts[k:])
    return left, right


# ============================================================
# 英語住所の判定
# ============================================================
def is_english_only(addr: str) -> bool:
    """
    日本語の文字が含まれず、英字を含むなら英文住所とみなす。
    """
    if not addr:
        return False
    return (not re.search(r"[一-龠ぁ-んァ-ヶｱ-ﾝー々〆ヵヶ]", addr)) and bool(
        re.search(r"[A-Za-z]", addr)
    )


# ============================================================
# 丁目・番・号・「の」→ ハイフン正規化
# ============================================================
def normalize_block_notation(s: str) -> str:
    """
    日本の住所で頻出の表記をハイフン連結に正規化する。
    例:
      3丁目2番5号 → 3-2-5
      1丁目4番地 → 1-4
      12の7       → 12-7
    """
    if not s:
        return s
    znum = r"[0-9０-９]+"

    # 長いものから順に置換
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番\s*({znum})\s*号", r"\1-\2-\3", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番地", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*丁目\s*({znum})\s*番(?!地)", r"\1-\2", s)
    s = re.sub(rf"({znum})\s*の\s*({znum})", r"\1-\2", s)
    return s


# ============================================================
# 建物語ローダ（JSON / フォールバック）
# ============================================================

# 埋め込みのデフォルト辞書（JSON が見つからないときの保険）
DEFAULT_BLDG_WORDS: List[str] = [
    # 以前ご共有いただいた語群をベースにした実用セット
    "ANNEX", "Bldg", "BLDG", "Bldg.", "BLDG.", "CABO", "MRビル", "Tower", "TOWER",
    "Trestage", "アーバン", "アネックス", "イースト", "ヴィラ", "ウェスト", "エクレール",
    "オフィス", "オリンピア", "ガーデン", "ガーデンタワー", "カミニート", "カレッジ",
    "カンファレンス", "キャッスル", "キング", "クルーセ", "ゲート", "ゲートシティ", "コート",
    "コープ", "コーポ", "サウス", "シティ", "シティタワー", "シャトレ", "スクウェア", "スクエア",
    "スタジアム", "スタジアムプレイス", "ステーション", "センター", "セントラル", "ターミナル",
    "タワー", "タワービル", "テラス", "ドーム", "ドミール", "トリトン", "ノース", "パーク",
    "ハイツ", "ハウス", "パルテノン", "パレス", "ビル", "ヒルズ", "ビルディング", "フォレスト",
    "プラザ", "プレイス", "プレステージュ", "フロント", "ホームズ", "マンション", "レジデンシャル",
    "レジデンス", "構内", "倉庫",
]

def load_bldg_words() -> List[str]:
    """
    data/bldg_words.json を優先的に探し、見つからなければ DEFAULT_BLDG_WORDS を返す。
    優先順:
      1) 環境変数 BLDG_WORDS_PATH で明示されたパス
      2) プロジェクトルート配下 data/bldg_words.json
      3) カレントディレクトリ配下 data/bldg_words.json
      4) 本ファイルと同階層の bldg_words.json
      5) Render の一般的な配置 /opt/render/project/src/data/bldg_words.json
    """
    candidates = [
        os.environ.get("BLDG_WORDS_PATH"),
        Path(__file__).resolve().parents[1] / "data" / "bldg_words.json",
        Path.cwd() / "data" / "bldg_words.json",
        Path(__file__).resolve().parent / "bldg_words.json",
        Path("/opt/render/project/src/data/bldg_words.json"),
    ]

    for p in candidates:
        if not p:
            continue
        p = Path(p)
        if p.is_file():
            try:
                with p.open("r", encoding="utf-8") as f:
                    words = json.load(f)
                if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
                    raise ValueError("bldg_words.json must be a JSON array of strings")
                logger.info("Loaded bldg_words.json: %s (%d words)", str(p), len(words))
                return words
            except Exception as e:
                logger.error("Failed to parse bldg_words.json at %s: %s", str(p), e)

    logger.error(
        "bldg_words.json not found. Falling back to DEFAULT_BLDG_WORDS (%d words)",
        len(DEFAULT_BLDG_WORDS),
    )
    return DEFAULT_BLDG_WORDS
