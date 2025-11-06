from converters.address import split_address

def test_split_basic():
    a1, a2 = split_address("東京都千代田区丸の内1-2-3 丸の内ビルディング 10F")
    assert a1 == "東京都千代田区丸の内1-2-3"
    assert "10" in a2

def test_split_no_bldg():
    a1, a2 = split_address("大阪府大阪市北区梅田3-1-1")
    assert a1 == "大阪府大阪市北区梅田3-1-1"
    assert a2 == ""

def test_split_dash_strip():
    a1, a2 = split_address("渋谷区宇田川町1-1 -ネコノスビル 2F")
    assert a1.endswith("1-1")
    assert not a2.startswith("-")
