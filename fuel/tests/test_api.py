import json
from pathlib import Path
from unittest import mock

import pytest
from django.core.cache import cache
from django.core.management import call_command

from fuel.services.ors import RoutingError
from fuel.services.station_index import reset_station_index

ROUTE = json.loads((Path(__file__).parent / "fixtures" / "route_nyc_la.json").read_text())


@pytest.fixture(autouse=True)
def stations(db):
    call_command("load_stations", verbosity=0)
    reset_station_index()
    cache.clear()
    yield
    reset_station_index()


@pytest.fixture
def ors():
    with mock.patch("fuel.services.planner.fetch_route", return_value=ROUTE) as m:
        yield m


def test_long_route_plan(client, ors):
    resp = client.post("/api/route/", {"start": "New York, NY", "finish": "Los Angeles, CA"}, content_type="application/json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    summary, stops = body["summary"], body["fuel_stops"]

    assert ors.call_count == 1
    assert body["meta"]["routing_api_calls"] == 1
    assert summary["total_gallons"] == pytest.approx(ROUTE["distance_miles"] / 10, abs=0.05)
    assert summary["total_fuel_cost"] == pytest.approx(sum(s["cost"] for s in stops), abs=0.05)
    assert summary["number_of_stops"] >= 6

    markers = [0.0] + [s["mile_marker"] for s in stops[1:]] + [summary["distance_miles"]]
    assert all(b - a <= 500.0 + 1e-6 for a, b in zip(markers, markers[1:]))
    assert all(s["gallons"] <= 50.0 + 1e-6 for s in stops)

    kinds = [f["properties"]["kind"] for f in body["map"]["geojson"]["features"]]
    assert kinds.count("route") == 1 and kinds.count("fuel_stop") == len(stops)
    assert "/api/route/map/?" in body["map"]["html_url"]


def test_repeated_request_uses_cache(client, ors):
    for _ in range(3):
        resp = client.get("/api/route/", {"start": "New York, NY", "finish": "Los Angeles, CA"})
        assert resp.status_code == 200
    assert ors.call_count == 1
    assert resp.json()["meta"] == {**resp.json()["meta"], "routing_api_calls": 0, "route_cached": True}


def test_map_page_renders_without_extra_calls(client, ors):
    client.get("/api/route/", {"start": "New York, NY", "finish": "Los Angeles, CA"})
    resp = client.get("/api/route/map/", {"start": "New York, NY", "finish": "Los Angeles, CA"})
    assert resp.status_code == 200
    assert b"leaflet" in resp.content and b"route-data" in resp.content
    assert ors.call_count == 1


def test_lat_lon_input(client, ors):
    resp = client.post("/api/route/", {"start": "40.7143,-74.0060", "finish": "34.0522,-118.2437"}, content_type="application/json")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"start": "New York, NY"},
        {"start": "Atlantis, ZZ", "finish": "Dallas, TX"},
        {"start": "Nowhereville, TX", "finish": "Dallas, TX"},
        {"start": "51.5,-0.12", "finish": "Dallas, TX"},
        {"start": "Dallas, TX", "finish": "Dallas, TX"},
    ],
)
def test_bad_input_is_400(client, ors, payload):
    resp = client.post("/api/route/", payload, content_type="application/json")
    assert resp.status_code == 400
    assert ors.call_count == 0


def test_routing_failure_is_502(client):
    with mock.patch("fuel.services.planner.fetch_route", side_effect=RoutingError("boom")):
        resp = client.post("/api/route/", {"start": "Chicago, IL", "finish": "Denver, CO"}, content_type="application/json")
    assert resp.status_code == 502


def test_cities_endpoint(client):
    resp = client.get("/api/cities/", {"state": "mo"})
    assert resp.status_code == 200
    cities = resp.json()["cities"]
    assert "St. Louis" in cities and "Kansas City" in cities
    assert client.get("/api/cities/", {"state": "ZZ"}).status_code == 400


def test_every_listed_city_resolves():
    from fuel.services.geocode import US_STATES, cities_for_state, resolve_location

    for state in US_STATES:
        for city in cities_for_state(state):
            resolve_location(f"{city}, {state}")


def test_planner_page(client, ors):
    resp = client.get("/")
    assert resp.status_code == 200 and b'id="start-state"' in resp.content
    assert ors.call_count == 0
    resp = client.get("/", {"start": "New York, NY", "finish": "Los Angeles, CA", "stop_cost": "0"})
    assert resp.status_code == 200 and b"route-data" in resp.content
    assert client.get("/", {"start": "Atlantis, ZZ", "finish": "Dallas, TX"}).status_code == 400
