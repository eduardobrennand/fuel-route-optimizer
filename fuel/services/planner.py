import hashlib
import time

import numpy as np
from django.conf import settings
from django.core.cache import cache

from .corridor import find_corridor, thin
from .geocode import resolve_location
from .optimizer import InfeasibleRoute, plan_refuels, plan_refuels_with_stop_cost
from .ors import fetch_route
from .station_index import get_station_index


class SameLocationError(ValueError):
    pass


def _route_cache_key(start, finish) -> str:
    raw = f"{start[0]:.5f},{start[1]:.5f}|{finish[0]:.5f},{finish[1]:.5f}"
    return "route:" + hashlib.sha1(raw.encode()).hexdigest()


def get_route(start, finish) -> tuple[dict, bool]:
    key = _route_cache_key(start, finish)
    route = cache.get(key)
    if route is not None:
        return route, True
    route = fetch_route(start, finish)
    cache.set(key, route)
    return route, False


def plan_trip(start_text: str, finish_text: str, stop_cost: float | None = None) -> dict:
    t0 = time.perf_counter()
    start, finish = resolve_location(start_text), resolve_location(finish_text)
    if np.allclose(start, finish, atol=1e-4):
        raise SameLocationError("Start and finish are the same place.")

    route, cached = get_route(start, finish)
    distance = route["distance_miles"]
    tank_range, mpg = settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG
    if stop_cost is None:
        stop_cost = settings.DEFAULT_STOP_COST_USD

    stations = get_station_index()
    corridor = find_corridor(route["coordinates"], stations, settings.CORRIDOR_RADIUS_MILES, distance)
    before_end = corridor.mile_markers < distance
    rows, miles, offsets = corridor.station_rows[before_end], corridor.mile_markers[before_end], corridor.offsets[before_end]
    if len(rows) == 0:
        raise InfeasibleRoute("No fuel stations found along this route.")

    positions = miles.copy()
    positions[0] = 0.0
    prices = stations.price[rows]
    if stop_cost > 0:
        purchases = plan_refuels_with_stop_cost(positions, prices / mpg, distance, tank_range, stop_cost)
    else:
        purchases = plan_refuels(positions, prices, distance, tank_range)

    stops = []
    for n, purchase in enumerate(purchases, start=1):
        row = rows[purchase.index]
        gallons = purchase.miles_of_fuel / mpg
        stops.append({
            "stop": n,
            **stations.info[row],
            "latitude": float(stations.lat[row]),
            "longitude": float(stations.lon[row]),
            "mile_marker": round(float(miles[purchase.index]), 1),
            "distance_from_route_miles": round(float(offsets[purchase.index]), 1),
            "price_per_gallon": round(float(prices[purchase.index]), 3),
            "gallons": round(gallons, 2),
            "cost": round(gallons * float(prices[purchase.index]), 2),
        })

    total_gallons = sum(p.miles_of_fuel for p in purchases) / mpg
    total_cost = sum(float(prices[p.index]) * p.miles_of_fuel / mpg for p in purchases)
    return {
        "start": {"query": start_text, "latitude": start[0], "longitude": start[1]},
        "finish": {"query": finish_text, "latitude": finish[0], "longitude": finish[1]},
        "summary": {
            "distance_miles": round(distance, 1),
            "duration_hours": round(route["duration_seconds"] / 3600, 2),
            "vehicle_range_miles": tank_range,
            "mpg": mpg,
            "stop_cost_usd": stop_cost,
            "total_gallons": round(total_gallons, 2),
            "total_fuel_cost": round(total_cost, 2),
            "number_of_stops": len(stops),
            "stations_considered": int(len(rows)),
        },
        "fuel_stops": stops,
        "route": {"type": "LineString", "coordinates": thin(route["coordinates"])},
        "meta": {
            "routing_api_calls": 0 if cached else 1,
            "route_cached": cached,
            "compute_ms": round((time.perf_counter() - t0) * 1000, 1),
        },
    }


def to_geojson(plan: dict) -> dict:
    features = [{"type": "Feature", "geometry": plan["route"], "properties": {"kind": "route", **plan["summary"]}}]
    for endpoint in ("start", "finish"):
        p = plan[endpoint]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["longitude"], p["latitude"]]},
            "properties": {"kind": endpoint, "name": p["query"]},
        })
    for stop in plan["fuel_stops"]:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [stop["longitude"], stop["latitude"]]},
            "properties": {"kind": "fuel_stop", **{k: v for k, v in stop.items() if k not in ("latitude", "longitude")}},
        })
    return {"type": "FeatureCollection", "features": features}
