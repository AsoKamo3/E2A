# Eight→宛名職人 変換 Fixed Baseline (2025-11-07, Asia/Tokyo)

## App & Services
- app.py ..................... v1.18  →  v1.20
- services/eight_to_atena.py . v2.33  →  v2.36

## Libraries
- converters/address.py ...... v1.1.0
- utils/textnorm.py .......... v1.16
- utils/kana.py .............. v1.1
- utils/jp_area_codes.py ..... v1.0.0

## Data
- data/bldg_words.json ................... v1.0.0
- data/corp_terms.json ................... v1.0.1

**企業名**
- data/company_kana_overrides_jp.json .... v1.0.0  →  v1.0.2
- data/company_kana_overrides_en.json .... v1.0.0  →  v1.0.1

**個人名**
- data/person_full_overrides.json ........ v1.0.0
- data/surname_kana_terms.json ........... v1.0.0  →  v1.0.1
- data/given_kana_terms.json ............. v1.0.0  →  v1.0.1

- data/company_kana_overrides.json ....... v1.1 // 未使用？


## Notes
- Address splitter = v17g 同等（辞書＋長語優先＋NFKC+lower、住所2先頭のダッシュ/空白除去）。コード版は `converters/address.py v1.1.0`。
- 宛名職人ヘッダは v2.27 準拠（完全列）を維持。電話は最長一致＋特番＋0補正。
- textnorm は to_zenkaku / to_zenkaku_wide / normalize_block_notation / normalize_postcode / load_bldg_words / bldg_words_version を提供。
