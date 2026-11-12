# UK Tick Sightings API

A backend service for a UK tick-sighting tracker, built as the Elanco Placement Program technical task.

It consumes raw crowdsourced tick-sighting data from the Elanco source API, cleans and validates it, stores it in a relational database, and exposes a REST API for searching, filtering and aggregate reporting (sightings per region and trends over time).

**Author:** Rumen Vasilev

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [API reference](#api-reference)
- [Data handling strategy](#data-handling-strategy)
- [Error handling](#error-handling)
- [Design decisions](#design-decisions)
- [Testing](#testing)
- [Configuration](#configuration)
- [What I would improve with more time](#what-i-would-improve-with-more-time)

---

## Features

- **ETL import pipeline:** fetches all sightings from the source API, validates and normalises every record, removes duplicates and bulk-upserts into the database. Safe to re-run (idempotent).
- **Resilient API client:** timeouts, retries with exponential backoff, rate-limit (HTTP 429) handling that respects `Retry-After`, and clear separation of temporary and permanent failures.
- **Data quality tracking:** invalid records are never silently dropped. They are stored with the raw payload and the reason they were rejected. Every import run is recorded in a sync log.
- **Search and filtering:** by date range, location and species (case-insensitive), with pagination and ordering.
- **Reporting:** sightings per region and weekly/monthly trends, both narrowable with the same filters.
- **Health endpoint:** reports database status, data freshness and the outcome of the last import, so the service degrades gracefully when the source API is down.
- **Consistent JSON errors** across the whole API.
- **Interactive API docs** (Swagger / OpenAPI) generated from the code.
- **Test suite** covering cleaning rules, the importer, client retry behaviour and every endpoint.

---

## Architecture

The system has two independent halves that meet only in the database:

```
            IMPORT (on demand / scheduled)                      SERVE (every request)

┌──────────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌─────────────┐   ┌────────┐
│ Elanco       │──▶│ Extract  │──▶│Transform │──▶│  Load    │──▶│  Database   │◀──│ Django │◀── Client
│ source API   │   │ client.py│   │cleaning.py│  │importer.py│  │ (SQLite)    │   │ REST   │
└──────────────┘   └──────────┘   └──────────┘   └──────────┘   └─────────────┘   │ API    │
                    retries,       validate,      dedupe,                          └────────┘
                    backoff,       normalise,     bulk upsert,                     filters, stats,
                    rate limits    reject bad     sync log                         health, docs
```

This is a classic **ETL (Extract, Transform, Load)** pattern. The public API never calls the source API directly, so:

- users are unaffected when the source API is slow, rate-limited or down;
- filtering by date range and aggregation, which the source API does not support, run as fast, indexed database queries;
- data is cleaned once, at import time, instead of on every request.

### Data model

```
Species (name, latin_name) ──┐
                             ├──< Sighting (source_id, date, location_id, species_id)
Location (name) ─────────────┘

RejectedRecord (source_id, raw_data, reason)      SyncLog (status, counts, timestamps, error)
```

- `Sighting.source_id` (the source API's ID) has a unique constraint, which enforces deduplication in the database itself.
- Species and locations are normalised into their own tables: a Latin name belongs to a species, not a sighting, and canonical location names mean region reports can't be split by spelling variants.
- Indexes on `date`, plus a composite index on `(location, date)`, match the most common query patterns.

### Project structure

```
tick_tracker/                  # Django project (settings, root URLs)
sightings/                     # Main app
├── models.py                  # Species, Location, Sighting, RejectedRecord, SyncLog
├── serializers.py             # Model → JSON
├── filters.py                 # Date range / location / species filters + validation
├── views.py                   # List, detail, stats and health endpoints
├── pagination.py
├── exceptions.py              # Consistent JSON error handler
├── urls.py
├── admin.py                   # Admin panel for browsing data and rejected records
├── services/
│   ├── client.py              # Extract: resilient source API client
│   ├── cleaning.py            # Transform: validation and normalisation rules
│   └── importer.py            # Load: dedupe + bulk upsert
├── management/commands/
│   └── import_sightings.py    # `python manage.py import_sightings`
└── tests/                     # pytest suite
```

---

## Getting started

### Prerequisites

- Python 3.12+
- Git

### Setup

```bash
git clone https://github.com/rumenvasil3v/Elanco-Placement-Backend/
cd ./tick-tracker/tick-tracker/

python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate            # create the database tables
python manage.py import_sightings   # fetch, clean and store the data
python manage.py runserver
```

Then open:

| URL | What |
|---|---|
| http://127.0.0.1:8000/api/docs/ | Interactive Swagger docs, where every endpoint can be tried |
| http://127.0.0.1:8000/api/sightings/ | Browsable API |
| http://127.0.0.1:8000/admin/ | Admin panel (run `python manage.py createsuperuser` first) |

Example import output:

```
Fetched 1000 | created 1000 | updated 0 | rejected 0 | duplicates in batch 0
```

Running the import again gives `created 0 | updated 1000`, confirming it is idempotent.

---

## API reference

All endpoints are read-only (`GET`) and public. Full, interactive documentation is at `/api/docs/`.

| Endpoint | Description |
|---|---|
| `GET /api/sightings/` | Paginated list of sightings, filterable |
| `GET /api/sightings/{id}/` | A single sighting by its source ID |
| `GET /api/locations/` | All locations with sighting counts |
| `GET /api/species/` | All species with Latin names and sighting counts |
| `GET /api/stats/regions/` | Number of sightings per region |
| `GET /api/stats/trends/` | Sighting counts per week or month |
| `GET /api/health/` | Service health and data freshness |

### Filters

`/api/sightings/`, `/api/stats/regions/` and `/api/stats/trends/` all accept:

| Parameter | Example | Notes |
|---|---|---|
| `start_date` | `2025-01-01` | Inclusive, `YYYY-MM-DD` |
| `end_date` | `2025-06-30` | Inclusive (the whole day is included) |
| `location` | `london` | Case-insensitive exact match |
| `species` | `southern rodent tick` | Case-insensitive exact match |

Plus, on `/api/sightings/`: `page`, `page_size` (max 500), `ordering` (`date` or `-date`).
Plus, on `/api/stats/trends/`: `interval` (`weekly` or `monthly`, default `monthly`).

### Examples

```
GET /api/sightings/?location=london&start_date=2025-01-01&end_date=2025-06-30
```
```json
{
  "count": 42,
  "next": "http://127.0.0.1:8000/api/sightings/?...&page=2",
  "previous": null,
  "results": [
    {
      "id": "Kq3x9ZfV2mTn8aL0pYwB",
      "date": "2025-06-14T17:30:00+01:00",
      "location": "London",
      "species": "Southern rodent tick",
      "latin_name": "Ixodes acuminatus"
    }
  ]
}
```

```
GET /api/stats/regions/?start_date=2025-01-01
```
```json
{
  "total": 312,
  "results": [
    { "region": "London", "count": 87 },
    { "region": "Manchester", "count": 54 }
  ]
}
```

```
GET /api/stats/trends/?interval=monthly&location=london
```
```json
{
  "interval": "monthly",
  "results": [
    { "period": "2025-01-01", "count": 4 },
    { "period": "2025-02-01", "count": 7 }
  ]
}
```

```
GET /api/health/?check_source=true
```
```json
{
  "status": "ok",
  "database": "ok",
  "sightings_stored": 1000,
  "data_is_stale": false,
  "last_sync": { "status": "success", "fetched": 1000, "created": 0, "updated": 1000, "rejected": 0, "...": "..." },
  "last_successful_sync_at": "2026-11-12T22:46:20Z",
  "source_api": "ok"
}
```

*(Counts in these examples are illustrative.)*

---

## Data handling strategy

### Consuming the source API

The source API exposes `/tick-sightings` (all records in one response), plus lookups by ID, city and species. The importer uses only the bulk endpoint: fetching record by record would mean hundreds of requests and would quickly hit the rate limit (HTTP 429). Filtering by city and species is done by this service's own database.

The source's `/stats` endpoint reports `total_sightings: 1000`, which matches the number of records fetched, confirming the full dataset is imported.

### Large datasets

- Records are validated in memory, then written with **bulk operations in batches of 500**. A full import takes a handful of queries rather than one per record.
- Existing-record lookups are chunked, to stay within database parameter limits.
- The whole load runs in a **single transaction**, so an import either completes fully or changes nothing.
- On the read side, all list endpoints are **paginated**, aggregations run in the database (`GROUP BY`), and `select_related` avoids N+1 queries.

### Duplicates

- **Across runs:** sightings are upserted on `source_id`, which has a unique constraint. Re-importing updates existing rows instead of duplicating them.
- **Within one batch:** if the same ID appears twice, the last occurrence wins and the count is reported (`duplicates_in_batch`).
- **Content duplicates** (same date, location and species under different IDs) were checked for in the current dataset and none were found. They are deliberately *not* merged automatically, because two people can genuinely see ticks in the same city at the same time.

### Incomplete and inconsistent data

Every record passes through `services/cleaning.py`:

| Rule | Behaviour |
|---|---|
| `id`, `date`, `location`, `species` missing or blank | Rejected |
| `latinName` missing | Accepted (optional) |
| Whitespace and casing in names | Normalised: `"  london "` → `"London"`, `"southern RODENT tick"` → `"Southern rodent tick"` |
| Date format | ISO 8601 first, then common fallbacks (`YYYY-MM-DD`, `DD/MM/YYYY`, …); unparseable dates are rejected |
| Date without time zone | Interpreted as UK time (`Europe/London`) |
| Date in the future | Rejected |
| Record isn't a JSON object | Rejected |

Rejected records are stored in `RejectedRecord` with the **original raw payload and the reason**, visible in the admin panel, so data issues can be audited and reported back to the source.

### Findings on the current dataset

- 1000 records, all with unique IDs: **0 rejected, 0 duplicate IDs, 0 content duplicates**.
- <!-- TODO: e.g. "N distinct locations and M species; X raw location spellings were merged into Y canonical names" -->

The dataset is currently clean, but the source is crowdsourced and will grow. The pipeline's handling of bad data is therefore proven by tests that feed in deliberately broken records (see [Testing](#testing)).

---

## Error handling

### Failures in the source API

Handled in `services/client.py`:

| Situation | Behaviour |
|---|---|
| Timeout / connection error | Retried |
| HTTP 5xx | Retried with exponential backoff (2s, 4s, 8s…, capped at 60s) |
| HTTP 429 rate limit | Waits for `Retry-After` (or 60s, as the API's message suggests), then retries |
| Other HTTP 4xx | **Not** retried. The request itself is wrong, so retrying won't help |
| Response isn't valid JSON / isn't a list | Fails immediately with a clear error |
| Still failing after 5 attempts | Raises `TickAPIError`; the import command exits cleanly and records a `failed` sync log |

Every retry is logged. **Existing data is never affected by a failed import**, so the API keeps serving the last good data.

### Errors from this API

A custom DRF exception handler (`exceptions.py`) gives every error the same shape:

```json
{
  "error": {
    "status": 400,
    "code": "invalid",
    "message": "Invalid request.",
    "details": { "start_date": ["Enter a valid date."] }
  }
}
```

- Invalid input (bad dates, start after end, unknown interval) → `400` with field-level details
- Unknown sighting → `404` with `"code": "not_found"`
- Unexpected bugs → `500` with a generic message; the full traceback is logged server-side and never exposed to clients

### Health and graceful degradation

`/api/health/` reports:

- `ok`: database reachable and the last import succeeded within the last 24 hours (configurable)
- `degraded`: data is still served, but the last import failed or the data is stale
- `503`: database unavailable

The source API is pinged only when `?check_source=true` is passed, with a single fast request and no retries, so monitoring does not use up the source's rate limit.

---

## Design decisions

**Django + Django REST Framework.** The ORM, migrations and admin panel come built in, which made it quick to build a reliable data layer and to inspect imported and rejected data. DRF provides serialisation, pagination, browsable endpoints and pluggable exception handling, and `drf-spectacular` generates OpenAPI docs from the code.

**ETL into a local database instead of proxying the source API.** The source API is rate-limited, can fail, and can't filter by date range or aggregate. Storing a cleaned copy makes the public API fast and independent of the source's availability.

**SQLite.** Zero setup for reviewers, and more than enough for this data volume. The code uses only the Django ORM, so switching to PostgreSQL is a settings change.

**Normalised `Species` and `Location` tables.** Avoids repeating Latin names on every sighting, guarantees one canonical spelling per location (so regional stats are accurate), and provides lookup endpoints for front-end filter dropdowns.

**Management command for imports.** Easy to run by hand, from cron, or from a task scheduler, and keeps import logic out of the request/response cycle.

**Public, read-only API.** Suits a public-awareness tool. Writes only happen through the controlled import pipeline. Authentication would be added if users could submit sightings directly.

**UK time zone for dates.** The source provides dates without a time zone; since this is a UK tracker, they are interpreted as `Europe/London` and stored in UTC.

---

## Testing

```bash
pytest -v
pytest --cov=sightings --cov-report=term-missing   # with coverage (pip install pytest-cov)
```

<!-- TODO: e.g. "XX tests, YY% coverage" -->

| File | Covers |
|---|---|
| `test_cleaning.py` | Every validation and normalisation rule, including missing fields, bad and future dates, and casing/whitespace |
| `test_importer.py` | Creating records, idempotent re-imports, duplicate IDs in a batch, storing rejected records, merging location variants |
| `test_client.py` | Retries on 500, 429 and connection errors, giving up after max retries, no retry on 4xx, invalid payloads. HTTP is mocked with `responses`, so no real API calls are made |
| `test_api.py` | Filters, date-range edge cases, pagination, 400/404 error format, regional stats, weekly/monthly trends, health statuses |

The tests caught a real bug during development: Django's `Http404` was returned with a generic error code instead of `not_found`, which was fixed in the exception handler.

---

## Configuration

Settings can be overridden with environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `TICK_API_BASE_URL` | `https://dev-task.elancoapps.com` | Source API |
| `TICK_API_TIMEOUT` | `30` | Request timeout (seconds) |
| `TICK_API_MAX_RETRIES` | `5` | Attempts before giving up |
| `DATA_STALE_AFTER_HOURS` | `24` | When `/api/health/` reports data as stale |

To simulate the source API being down:

```bash
TICK_API_BASE_URL=http://localhost:9999 TICK_API_MAX_RETRIES=2 python manage.py import_sightings
```

The import fails cleanly, `/api/health/` shows `degraded`, and `/api/sightings/` still serves all stored data.

---

## What I would improve with more time

- **Scheduled imports:** run the import automatically (Celery Beat, or cron in production) instead of on demand.
- **Incremental sync:** the source API has no "changed since" parameter, so every import fetches everything. With source support, only new or updated records would be fetched.
- **PostgreSQL + Docker Compose** for a production-like setup.
- **Geographic data:** add coordinates and broader UK regions to `Location`, enabling map visualisation (like the Parvovirus Tracker) and region-level aggregation.
- **Caching** of stats endpoints (e.g. Redis), invalidated after each import.
- **Handling of sightings deleted at the source:** currently records missing from a new import are kept; a soft-delete flag would track them.
- **Fuzzy matching of location names** (e.g. "Newcastle" vs "Newcastle upon Tyne").
- **AI/ML insights:** forecasting sightings per region and flagging unusual spikes.
- **CI pipeline** (GitHub Actions) running tests and linting on every push.
- **Authentication and rate limiting** on this API, if write endpoints or heavier public use were added.
