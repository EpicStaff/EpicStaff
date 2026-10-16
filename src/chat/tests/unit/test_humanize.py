import pytest
from common.humanize import Rate, to_rate


@pytest.mark.parametrize(
    ("value", "rate"),
    [
        ("30/m", Rate(30, 60)),
        ("20/h", Rate(20, 3600)),
        ("5/s", Rate(5, 1)),
        ("1000/d", Rate(1000, 86400)),
        (" 30 / M ", Rate(30, 60)),
    ],
)
def test_to_rate_reads_count_per_unit(value, rate):
    assert to_rate(value) == rate


@pytest.mark.parametrize("value", ["30", "30m", "/m", "30/", "30/w", "1.5/m", "-1/m", "0/m", "00/h", "30/5m", "thirty/m", "30//m"])
def test_to_rate_rejects_bad_input(value):
    with pytest.raises(ValueError):
        to_rate(value)
