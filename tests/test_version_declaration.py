def test_the_daily_dataset_names_the_us_equity_calendar() -> None:
    """v24's calendar_id (the plan's O10), on this plugin's move to v25: the
    daily closes' business dates follow the platform's US equity venues
    calendar."""
    from tradier.declared import CATALOGUE, US_EQUITY_CALENDAR

    assert US_EQUITY_CALENDAR == "CAL-01M4VF0F4XGP3RATCCSKDPZSBP"
    (daily,) = [dataset for dataset in CATALOGUE if dataset.key == "daily"]
    assert daily.calendar_id == US_EQUITY_CALENDAR


def test_the_option_chains_datasets_name_the_us_equity_calendar() -> None:
    """0.13.2 (ruling 768): `options` and `options_delayed` declare the US
    equity and options holiday calendar `daily` declares, so their closed
    days are known and a series quoted at no venue is placed by it."""
    from tradier.declared import CATALOGUE, US_EQUITY_CALENDAR

    chains = {
        dataset.key: dataset.calendar_id
        for dataset in CATALOGUE
        if dataset.key in ("options", "options_delayed")
    }
    assert chains == {
        "options": US_EQUITY_CALENDAR,
        "options_delayed": US_EQUITY_CALENDAR,
    }
