from server.core.period_utils import normalize_period_text


def test_normalize_period_text():
    assert normalize_period_text("2023-05-12 ,  2023-06-12") == "2023-05-12, 2023-06-12"
    assert normalize_period_text("2022-04-01 01:00, 2022-05-26 01:00") == "2022-04-01, 2022-05-26"
