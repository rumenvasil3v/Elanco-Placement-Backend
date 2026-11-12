"""
Validation and normalisation rules for raw sighting records.

Each raw dict from the API either becomes a CleanSighting or raises
ValidationError with a human-readable reason (which we store).
"""
import re
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

REQUIRED_FIELDS = ("id", "date", "location", "species")
FALLBACK_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M")


class ValidationError(Exception):
    """A raw record can't be turned into a valid sighting."""


@dataclass(frozen=True)
class CleanSighting:
    source_id: str
    date: datetime
    location: str
    species: str
    latin_name: str


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalise_location(value):
    return clean_text(value).title()


def normalise_sentence_case(value):
    text = clean_text(value)
    return text[:1].upper() + text[1:].lower() if text else ""


def parse_date(value):
    text = clean_text(value)
    if not text:
        raise ValidationError("missing date")

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in FALLBACK_DATE_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValidationError(f"unrecognised date format: {text!r}")

    # The API gives no time zone; treat it as UK time (settings.TIME_ZONE)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)

    if dt > timezone.now():
        raise ValidationError(f"date is in the future: {text!r}")
    return dt


def clean_record(raw):
    if not isinstance(raw, dict):
        raise ValidationError(f"record is not an object: {type(raw).__name__}")

    missing = [f for f in REQUIRED_FIELDS if not clean_text(raw.get(f))]
    if missing:
        raise ValidationError(f"missing required field(s): {', '.join(missing)}")

    return CleanSighting(
        source_id=clean_text(raw["id"]),
        date=parse_date(raw["date"]),
        location=normalise_location(raw["location"]),
        species=normalise_sentence_case(raw["species"]),
        latin_name=normalise_sentence_case(raw.get("latinName")),
    )