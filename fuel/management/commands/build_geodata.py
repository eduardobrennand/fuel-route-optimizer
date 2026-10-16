import csv
import io
import re
import time
import zipfile

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from fuel.services.geocode import US_STATES, normalize_city

GAZETTEER_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_{kind}_national.zip"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "fuel-route-optimizer/1.0 (one-off data prep)"


def _place_base_name(name: str) -> str:
    name = re.sub(r"\s*\(.*?\)", "", name)
    words = name.split()
    while len(words) > 1 and (words[-1].islower() or words[-1] in ("CDP", "CCD")):
        words.pop()
    return " ".join(words)


class Command(BaseCommand):
    help = "Build data/us_places.csv and data/stations_geocoded.csv (requires internet)."

    def handle(self, *args, **options):
        data_dir = settings.DATA_DIR
        places = self._build_places()
        self._write_places(places, data_dir / "us_places.csv")

        stations = self._read_stations(data_dir / "fuel_prices.csv")
        overrides = self._read_overrides(data_dir / "city_overrides.csv")

        missing = sorted(
            {(s["state"], s["city"]) for s in stations}
            - {(st, c) for st, c in overrides}
            - {(st, c) for st, c in ((s["state"], s["city"]) for s in stations) if (st, normalize_city(c)) in places}
        )
        if missing:
            self.stdout.write(f"Resolving {len(missing)} cities not in the Gazetteer via Nominatim...")
            self._resolve_with_nominatim(missing, overrides, data_dir / "city_overrides.csv")

        written = unresolved = 0
        with open(data_dir / "stations_geocoded.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["opis_id", "name", "address", "city", "state", "price", "lat", "lon"])
            writer.writeheader()
            for s in stations:
                place = places.get((s["state"], normalize_city(s["city"])))
                coords = place[:2] if place else overrides.get((s["state"], s["city"]))
                if coords is None:
                    unresolved += 1
                    continue
                writer.writerow({**s, "lat": f"{coords[0]:.6f}", "lon": f"{coords[1]:.6f}"})
                written += 1

        self.stdout.write(self.style.SUCCESS(f"{written} US stations geocoded, {unresolved} dropped (unresolvable city)."))

    def _build_places(self) -> dict[tuple[str, str], tuple[float, float, str, bool]]:
        best: dict[tuple[str, str], tuple] = {}
        for priority, kind in enumerate(("place", "cousubs")):
            self.stdout.write(f"Downloading Gazetteer '{kind}'...")
            resp = requests.get(GAZETTEER_URL.format(kind=kind), timeout=60)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                text = zf.read(zf.namelist()[0]).decode("utf-8")
            for row in csv.DictReader(io.StringIO(text), delimiter="|"):
                row = {k.strip(): v.strip() for k, v in row.items()}
                if row["USPS"] not in US_STATES:
                    continue
                base = _place_base_name(row["NAME"])
                aliases = {base}
                if "-" in base:  # "Nashville-Davidson" is known as "Nashville"
                    aliases.add(base.split("-")[0])
                if base.endswith(" City"):  # "Boise City" is known as "Boise"
                    aliases.add(base[: -len(" City")])
                for alias in aliases:
                    is_alias = alias != base
                    candidate = (
                        priority, is_alias, -float(row["ALAND"]),
                        float(row["INTPTLAT"]), float(row["INTPTLONG"]), alias, priority == 0 and not is_alias,
                    )
                    key = (row["USPS"], normalize_city(alias))
                    if key not in best or candidate < best[key]:
                        best[key] = candidate
        return {key: (lat, lon, name, listed) for key, (_, _, _, lat, lon, name, listed) in best.items()}

    @staticmethod
    def _write_places(places, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["state", "key", "name", "listed", "lat", "lon"])
            for (state, key), (lat, lon, name, listed) in sorted(places.items()):
                writer.writerow([state, key, name, int(listed), f"{lat:.5f}", f"{lon:.5f}"])

    @staticmethod
    def _read_stations(path) -> list[dict]:
        by_id: dict[int, dict] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                state = row["State"].strip()
                if state not in US_STATES:
                    continue
                station = {
                    "opis_id": int(row["OPIS Truckstop ID"]),
                    "name": row["Truckstop Name"].strip(),
                    "address": row["Address"].strip(),
                    "city": row["City"].strip(),
                    "state": state,
                    "price": float(row["Retail Price"]),
                }
                current = by_id.get(station["opis_id"])
                if current is None or station["price"] < current["price"]:
                    by_id[station["opis_id"]] = station
        return list(by_id.values())

    @staticmethod
    def _read_overrides(path) -> dict[tuple[str, str], tuple[float, float]]:
        if not path.exists():
            return {}
        with open(path, newline="", encoding="utf-8") as f:
            return {(r["state"], r["city"]): (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)}

    def _resolve_with_nominatim(self, missing, overrides, path):
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        for state, city in missing:
            time.sleep(1.1)  # Nominatim: max 1 req/s
            resp = session.get(
                NOMINATIM_URL,
                params={"city": city, "state": state, "country": "us", "format": "json", "limit": 1},
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                overrides[(state, city)] = (float(results[0]["lat"]), float(results[0]["lon"]))
            else:
                self.stdout.write(self.style.WARNING(f"  not found: {city}, {state}"))
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["state", "city", "lat", "lon"])
            for (state, city), (lat, lon) in sorted(overrides.items()):
                writer.writerow([state, city, f"{lat:.6f}", f"{lon:.6f}"])
