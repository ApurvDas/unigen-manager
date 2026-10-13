import version


def test_bump_rolls_over_after_9():
    assert version.bump("1.0.0") == "1.0.1"
    assert version.bump("1.0.8") == "1.0.9"
    assert version.bump("1.0.9") == "1.1.0"
    assert version.bump("1.9.9") == "2.0.0"


def test_current_version_is_valid():
    assert all(0 <= int(p) <= 9 for p in version.VERSION.split("."))
