from cfu_counter.naming import parse


def test_parse_standard():
    m = parse("P01V18_G+_YM_1X_aer_day9_1_20260521_162517.jpg")
    assert m is not None
    assert m.plate == "P01V18"
    assert m.gram == "G+"
    assert m.medium == "YM"
    assert m.dilution == "1X"
    assert m.atmo == "aer"
    assert m.day == 9
    assert m.rep == 1
    assert m.timestamp == "2026-05-21T16:25:17"


def test_parse_anaerobic_gminus():
    m = parse("P06V18_G-_YM_1X_ana_day9_5_20260521_165103.jpg")
    assert m is not None
    assert m.gram == "G-"
    assert m.atmo == "ana"
    assert m.rep == 5


def test_parse_jpeg_extension():
    assert parse("P01V18_G+_YM_1X_aer_day9_1_20260521_162517.jpeg") is not None


def test_parse_returns_none_for_bad_name():
    assert parse("random_file.jpg") is None
    assert parse("P01_G+_YM_1X_aer_day9_1_20260521_162517.jpg") is None  # missing VNN
