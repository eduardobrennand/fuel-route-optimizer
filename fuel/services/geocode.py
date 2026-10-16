import csv
import re
import unicodedata
from functools import lru_cache

from django.conf import settings

US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
    "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)

_ABBREVIATIONS = [
    (r"\bst\.?\s", "saint "),
    (r"\bste\.?\s", "sainte "),
    (r"\bft\.?\s", "fort "),
    (r"\bmt\.?\s", "mount "),
]
_LAT_LON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_US_BBOX = (18.0, 72.0, -180.0, -66.0)


class GeocodeError(ValueError):
    pass


def normalize_city(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip() + " "
    for pattern, replacement in _ABBREVIATIONS:
        s = re.sub(pattern, replacement, s)
    return re.sub(r"[^a-z0-9]", "", s)


@lru_cache(maxsize=1)
def _places() -> dict[tuple[str, str], tuple[float, float]]:
    with open(settings.DATA_DIR / "us_places.csv", newline="", encoding="utf-8") as f:
        return {(r["state"], r["key"]): (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def _listed_cities() -> dict[str, list[str]]:
    by_state: dict[str, set[str]] = {}
    with open(settings.DATA_DIR / "us_places.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["listed"] == "1":
                by_state.setdefault(r["state"], set()).add(r["name"])
    return {state: sorted(names, key=str.casefold) for state, names in by_state.items()}


def cities_for_state(state: str) -> list[str]:
    return _listed_cities().get(state.strip().upper(), [])


def lookup_city(city: str, state: str) -> tuple[float, float] | None:
    return _places().get((state.strip().upper(), normalize_city(city)))


def resolve_location(text: str) -> tuple[float, float]:
    if not isinstance(text, str) or not text.strip():
        raise GeocodeError("Location must be a non-empty string like 'Chicago, IL' or '41.88,-87.63'.")

    if m := _LAT_LON_RE.match(text):
        lat, lon = float(m.group(1)), float(m.group(2))
        lat_min, lat_max, lon_min, lon_max = _US_BBOX
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            raise GeocodeError(f"Coordinates {text!r} are outside the USA.")
        return lat, lon

    city, sep, state = text.rpartition(",")
    state = state.strip().upper()
    if not sep or not city.strip() or state not in US_STATES:
        raise GeocodeError(f"Could not parse {text!r}. Use 'City, ST' (e.g. 'Dallas, TX') or 'lat,lon'.")

    coords = lookup_city(city, state)
    if coords is None:
        raise GeocodeError(f"Unknown US city {text!r}. Try a nearby larger city or pass 'lat,lon'.")
    return coords
