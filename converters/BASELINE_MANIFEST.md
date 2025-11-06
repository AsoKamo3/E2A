# Eight→宛名職人 変換 Fixed Baseline (2025-11-07, Asia/Tokyo)

## App & Services
- app.py ..................... v1.18
- services/eight_to_atena.py . v2.31

## Libraries
- converters/address.py ...... v1.1.0
- utils/textnorm.py .......... v1.15
- utils/kana.py .............. v1.0
- utils/jp_area_codes.py ..... v1.0.0

## Data
- data/bldg_words.json ....... v1.0.0
- data/corp_terms.json ....... v1.0.1
- data/company_kana_overrides.json ... v1.1

## Notes
- Address splitter = v17g 同等（辞書＋長語優先＋NFKC+lower、住所2先頭のダッシュ/空白除去）
- 宛名職人ヘッダは v2.27 準拠（完全列）を維持。電話は最長一致＋特番＋0補正。
