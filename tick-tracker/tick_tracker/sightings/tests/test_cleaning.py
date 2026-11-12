from datetime import timedelta

import pytest
from django.utils import timezone

from sightings.services.cleaning import ValidationError, clean_record

VALID = {
    "id": "abc123",
    "date": "2025-08-14T17:30:00",
    "location": "London",
    "species": "Southern rodent tick",
    "latinName": "Ixodes acuminatus",
}


def make(**overrides):
    return {**VALID, **overrides}


def test_valid_record_is_cleaned():
    r = clean_record(VALID)
    assert r.source_id == "abc123"
    assert r.location == "London"
    assert r.species == "Southern rodent tick"
    assert r.latin_name == "Ixodes acuminatus"
    assert r.date.year == 2025 and timezone.is_aware(r.date)


@pytest.mark.parametrize("raw, expected", [
    ("  london ", "London"),
    ("LONDON", "London"),
    ("milton   keynes", "Milton Keynes"),
])
def test_location_is_normalised(raw, expected):
    assert clean_record(make(location=raw)).location == expected


def test_species_is_sentence_cased():
    assert clean_record(make(species="southern RODENT tick")).species == "Southern rodent tick"


@pytest.mark.parametrize("field", ["id", "date", "location", "species"])
@pytest.mark.parametrize("bad_value", [None, "", "   "])
def test_missing_required_field_is_rejected(field, bad_value):
    with pytest.raises(ValidationError, match=field):
        clean_record(make(**{field: bad_value}))


def test_missing_latin_name_is_allowed():
    assert clean_record(make(latinName=None)).latin_name == ""


@pytest.mark.parametrize("date", ["2025-08-14", "14/08/2025", "2025-08-14 17:30:00"])
def test_alternative_date_formats_are_accepted(date):
    assert clean_record(make(date=date)).date.month == 8


def test_unparseable_date_is_rejected():
    with pytest.raises(ValidationError, match="unrecognised date"):
        clean_record(make(date="not-a-date"))


def test_future_date_is_rejected():
    future = (timezone.localtime() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    with pytest.raises(ValidationError, match="future"):
        clean_record(make(date=future))


def test_non_dict_record_is_rejected():
    with pytest.raises(ValidationError):
        clean_record("garbage")