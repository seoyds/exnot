from exnot.discovery.url_patterns import derive_url_pattern, match_url_pattern


def test_derive_pattern_from_pdf_url():
    url = "https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/NYSE_Arca_Options_Fee_Schedule.pdf"
    pattern = derive_url_pattern(url)
    assert pattern is not None
    assert "nyse.com" in pattern
    assert "Fee" in pattern or "fee" in pattern.lower()


def test_derive_pattern_from_html_url():
    url = "https://www.cboe.com/us/options/membership/fee_schedule/"
    pattern = derive_url_pattern(url)
    assert pattern is not None
    assert "cboe.com" in pattern


def test_match_url_pattern():
    pattern = derive_url_pattern(
        "https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/NYSE_Arca_Options_Fee_Schedule.pdf"
    )
    assert match_url_pattern(
        pattern, "https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/NYSE_Arca_Options_Fee_Schedule.pdf"
    )


def test_match_pattern_with_version_change():
    pattern = derive_url_pattern("https://exchange.com/docs/fee_schedule_2025.pdf")
    assert match_url_pattern(pattern, "https://exchange.com/docs/fee_schedule_2026.pdf")


def test_no_match_different_domain():
    pattern = derive_url_pattern("https://exchange.com/docs/fee_schedule.pdf")
    assert not match_url_pattern(pattern, "https://other.com/docs/fee_schedule.pdf")


def test_derive_pattern_returns_none_for_invalid():
    assert derive_url_pattern("not-a-url") is None
    assert derive_url_pattern("") is None


def test_match_with_none_pattern():
    assert not match_url_pattern(None, "https://example.com")
