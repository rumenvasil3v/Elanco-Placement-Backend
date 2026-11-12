import logging
from dataclasses import dataclass

from django.db import transaction

from ..models import Location, RejectedRecord, Sighting, Species
from .cleaning import ValidationError, clean_record

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


@dataclass
class ImportResult:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    rejected: int = 0
    duplicates_in_batch: int = 0


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def import_sightings(raw_records):
    result = ImportResult(fetched=len(raw_records))
    valid = {}       # source_id -> CleanSighting
    rejected = []    # RejectedRecord objects (not saved yet)

    # 1. Clean every record; collect rejects with their reason
    for raw in raw_records:
        try:
            record = clean_record(raw)
        except ValidationError as exc:
            source_id = str(raw.get("id", "")) if isinstance(raw, dict) else ""
            rejected.append(RejectedRecord(source_id=source_id, raw_data=raw, reason=str(exc)))
            continue
        if record.source_id in valid:
            result.duplicates_in_batch += 1
        valid[record.source_id] = record

    result.rejected = len(rejected)

    with transaction.atomic(): 
        location_names = {r.location for r in valid.values()}
        Location.objects.bulk_create(
            [Location(name=n) for n in location_names], ignore_conflicts=True
        )
        locations = {l.name: l for l in Location.objects.filter(name__in=location_names)}

        species_latin = {}
        for r in valid.values():
            if r.latin_name and not species_latin.get(r.species):
                species_latin[r.species] = r.latin_name
            species_latin.setdefault(r.species, "")
        Species.objects.bulk_create(
            [Species(name=n, latin_name=l) for n, l in species_latin.items()],
            ignore_conflicts=True,
        )
        species = {s.name: s for s in Species.objects.filter(name__in=species_latin)}

        ids = list(valid)
        existing = set()
        for chunk in _chunks(ids, BATCH_SIZE):
            existing.update(
                Sighting.objects.filter(source_id__in=chunk).values_list("source_id", flat=True)
            )
        result.updated = len(existing)
        result.created = len(ids) - len(existing)

        # 4. Upsert sightings in batches
        objs = [
            Sighting(
                source_id=r.source_id,
                date=r.date,
                location=locations[r.location],
                species=species[r.species],
            )
            for r in valid.values()
        ]
        Sighting.objects.bulk_create(
            objs,
            batch_size=BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["source_id"],
            update_fields=["date", "location", "species", "updated_at"],
        )

        RejectedRecord.objects.bulk_create(rejected, batch_size=BATCH_SIZE)

    logger.info("Import finished: %s", result)
    return result