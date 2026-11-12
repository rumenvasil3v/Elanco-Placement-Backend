import pytest
import requests
import responses
from django.conf import settings

from sightings.services.client import TickAPIClient, TickAPIError

BASE = "https://example.test"
URL = f"{BASE}/tick-sightings"


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch):
    """Skip the backoff sleeps so tests run instantly."""
    monkeypatch.setattr(TickAPIClient._get.retry, "sleep", lambda seconds: None)


@pytest.fixture
def client():
    return TickAPIClient(base_url=BASE, timeout=1)


@responses.activate
def test_returns_sightings(client):
    responses.get(URL, json=[{"id": "a"}])
    assert client.get_all_sightings() == [{"id": "a"}]


@responses.activate
def test_retries_on_500_then_succeeds(client):
    responses.get(URL, status=500, json={"error": "Internal server error"})
    responses.get(URL, status=500, json={"error": "Internal server error"})
    responses.get(URL, json=[{"id": "a"}])
    assert client.get_all_sightings() == [{"id": "a"}]
    assert len(responses.calls) == 3


@responses.activate
def test_retries_after_rate_limit(client):
    responses.get(URL, status=429, headers={"Retry-After": "1"},
                  json={"error": "Rate limit exceeded, please try again later"})
    responses.get(URL, json=[])
    assert client.get_all_sightings() == []
    assert len(responses.calls) == 2


@responses.activate
def test_retries_on_connection_error(client):
    responses.get(URL, body=requests.ConnectionError("network down"))
    responses.get(URL, json=[])
    assert client.get_all_sightings() == []


@responses.activate
def test_gives_up_after_max_retries(client):
    responses.get(URL, status=500)
    with pytest.raises(TickAPIError):
        client.get_all_sightings()
    assert len(responses.calls) == settings.TICK_API_MAX_RETRIES


@responses.activate
def test_client_errors_are_not_retried(client):
    responses.get(URL, status=404)
    with pytest.raises(TickAPIError):
        client.get_all_sightings()
    assert len(responses.calls) == 1


@responses.activate
def test_unexpected_payload_shape_is_rejected(client):
    responses.get(URL, json={"not": "a list"})
    with pytest.raises(TickAPIError, match="Expected a list"):
        client.get_all_sightings()


@responses.activate
def test_invalid_json_is_rejected(client):
    responses.get(URL, body="<html>oops</html>", status=200)
    with pytest.raises(TickAPIError, match="Invalid JSON"):
        client.get_all_sightings()