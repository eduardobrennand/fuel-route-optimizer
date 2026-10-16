import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class RoutingError(Exception):
    pass


class RouteNotFound(RoutingError):
    pass


def fetch_route(start: tuple[float, float], finish: tuple[float, float]) -> dict:
    if not settings.ORS_API_KEY:
        raise RoutingError("ORS_API_KEY is not configured.")

    url = f"{settings.ORS_BASE_URL}/v2/directions/driving-car/geojson"
    body = {
        "coordinates": [[start[1], start[0]], [finish[1], finish[0]]],
        "units": "mi",
        "instructions": False,
        "preference": "recommended",
    }
    logger.info("ORS directions request %s -> %s", start, finish)
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"Authorization": settings.ORS_API_KEY, "Accept": "application/geo+json"},
            timeout=settings.ORS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RoutingError(f"Routing service unreachable: {exc}") from exc

    if resp.status_code == 404 or (resp.status_code == 400 and "route" in resp.text.lower()):
        raise RouteNotFound("No drivable route found between the given locations.")
    if resp.status_code != 200:
        raise RoutingError(f"Routing service error {resp.status_code}: {resp.text[:200]}")

    feature = resp.json()["features"][0]
    summary = feature["properties"].get("summary", {})
    return {
        "coordinates": feature["geometry"]["coordinates"],
        "distance_miles": float(summary.get("distance", 0.0)),
        "duration_seconds": float(summary.get("duration", 0.0)),
    }
