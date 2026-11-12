import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from sightings.models import SyncLog
from sightings.services.importer import import_sightings


def rec(source_id, date, location="London", species="Southern rodent tick",
        latin="Ixodes acuminatus"):
    return {"id": source_id, "date": date, "location": location,
            "species": species, "latinName": latin}


@pytest.fixture
def data(db):
    import_sightings([
        rec("a", "2025-01-10T10:00:00"),
        rec("b", "2025-01-20T10:00:00"),
        rec("c", "2025-02-05T10:00:00", location="Leeds",
            species="Castor bean tick", latin="Ixodes ricinus"),
    ])


@pytest.fixture
def api():
    return APIClient()


def ids(response):
    return {s["id"] for s in response.json()["results"]}


# ---- list + filters ------------------------------------------------------------

def test_list_is_paginated(api, data):
    r = api.get("/api/sightings/")
    assert r.status_code == 200
    assert r.json()["count"] == 3


def test_filter_by_location_is_case_insensitive(api, data):
    assert ids(api.get("/api/sightings/?location=london")) == {"a", "b"}


def test_filter_by_date_range(api, data):
    r = api.get("/api/sightings/?start_date=2025-01-15&end_date=2025-02-28")
    assert ids(r) == {"b", "c"}


def test_end_date_is_inclusive(api, data):
    assert ids(api.get("/api/sightings/?end_date=2025-01-20")) == {"a", "b"}


def test_filter_by_species(api, data):
    assert ids(api.get("/api/sightings/?species=castor bean tick")) == {"c"}


def test_invalid_date_returns_standard_400(api, data):
    r = api.get("/api/sightings/?start_date=banana")
    assert r.status_code == 400
    body = r.json()["error"]
    assert body["status"] == 400
    assert "start_date" in body["details"]


def test_start_after_end_returns_400(api, data):
    r = api.get("/api/sightings/?start_date=2025-06-01&end_date=2025-01-01")
    assert r.status_code == 400


# ---- detail ------------------------------------------------------------------

def test_detail_returns_sighting(api, data):
    r = api.get("/api/sightings/c/")
    assert r.status_code == 200
    assert r.json()["location"] == "Leeds"
    assert r.json()["latin_name"] == "Ixodes ricinus"


def test_unknown_sighting_returns_404(api, data):
    r = api.get("/api/sightings/nope/")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ---- stats -------------------------------------------------------------------

def test_stats_by_region(api, data):
    body = api.get("/api/stats/regions/").json()
    assert body["total"] == 3
    assert body["results"] == [
        {"region": "London", "count": 2},
        {"region": "Leeds", "count": 1},
    ]


def test_stats_respect_filters(api, data):
    body = api.get("/api/stats/regions/?start_date=2025-02-01").json()
    assert body["results"] == [{"region": "Leeds", "count": 1}]


def test_monthly_trends(api, data):
    body = api.get("/api/stats/trends/?interval=monthly").json()
    assert body["results"] == [
        {"period": "2025-01-01", "count": 2},
        {"period": "2025-02-01", "count": 1},
    ]


def test_weekly_trends_have_one_row_per_week(api, data):
    body = api.get("/api/stats/trends/?interval=weekly").json()
    assert sum(r["count"] for r in body["results"]) == 3
    assert len(body["results"]) == 3  # the three dates fall in different weeks


def test_invalid_interval_returns_400(api, data):
    assert api.get("/api/stats/trends/?interval=yearly").status_code == 400


# ---- health ------------------------------------------------------------------

def test_health_is_degraded_before_any_sync(api, db):
    body = api.get("/api/health/").json()
    assert body["status"] == "degraded"
    assert body["data_is_stale"] is True


def test_health_is_ok_after_recent_successful_sync(api, data):
    SyncLog.objects.create(status="success", finished_at=timezone.now())
    body = api.get("/api/health/").json()
    assert body["status"] == "ok"
    assert body["sightings_stored"] == 3


def test_health_is_degraded_after_failed_sync(api, data):
    SyncLog.objects.create(status="success", finished_at=timezone.now())
    SyncLog.objects.create(status="failed", finished_at=timezone.now(), error_message="API down")
    body = api.get("/api/health/").json()
    assert body["status"] == "degraded"
    assert body["last_sync"]["error_message"] == "API down"