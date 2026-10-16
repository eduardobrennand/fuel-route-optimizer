# Fuel Route Optimizer

A Django API that takes a start and a finish location in the USA and returns:

- the driving route, as GeoJSON plus an interactive map page,
- the most cost-effective fuel stops along the way (500-mile range, tank starts empty),
- the gallons bought at each stop and the **total fuel cost** (10 mpg).

Each request makes **at most one** call to the routing API ([OpenRouteService](https://openrouteservice.org)), and repeated routes make none. A cross-country plan is computed in about 10 ms once the route is known.

## Quickstart

```bash
uv sync                                   # Python 3.13, Django 6.1, DRF 3.18
cp .env.example .env                      # then set ORS_API_KEY (free: https://openrouteservice.org/dev/#/signup)
uv run python manage.py migrate
uv run python manage.py load_stations     # loads 6,626 geocoded US stations (offline, ~1 s)
uv run python manage.py runserver
```

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

Or open **http://127.0.0.1:8000/** for the web planner: pick a state and city for the start and the finish, and the route, the stops and the totals appear on the map. The returned `map.html_url` opens the same page for an API result. A Postman collection is in [`postman_collection.json`](postman_collection.json).

Run the tests with `uv run pytest`. They don't need an API key because the routing call is mocked with a recorded NY → LA route.

## API

### `POST /api/route/` (or `GET` with query params)

| field       | required | description                                                                          |
|-------------|----------|--------------------------------------------------------------------------------------|
| `start`     | yes      | `"City, ST"` (e.g. `"Chicago, IL"`) or `"lat,lon"`                                     |
| `finish`    | yes      | same                                                                                 |
| `stop_cost` | no       | Penalty in USD per fuel stop (default `10`). `0` means the cheapest fuel, however many stops it takes. |

Response (abridged):

```json
{
  "summary": {
    "distance_miles": 2793.9, "duration_hours": 49.78, "vehicle_range_miles": 500.0, "mpg": 10.0,
    "stop_cost_usd": 10.0, "total_gallons": 279.4, "total_fuel_cost": 860.14,
    "number_of_stops": 7, "stations_considered": 459
  },
  "fuel_stops": [
    {"stop": 1, "name": "DELTA", "address": "...", "city": "Jersey City", "state": "NJ",
     "mile_marker": 3.0, "distance_from_route_miles": 1.5, "price_per_gallon": 3.239,
     "gallons": 38.7, "cost": 125.35, "latitude": 40.71, "longitude": -74.06, "opis_id": 1234}
  ],
  "map": {"html_url": "http://127.0.0.1:8000/api/route/map/?start=...", "geojson": {"type": "FeatureCollection", "features": ["..."]}},
  "meta": {"routing_api_calls": 1, "route_cached": false, "compute_ms": 128.8}
}
```

Errors: `400` for input that is invalid or can't be resolved, `422` when no route exists or the gaps between stations are too long, and `502` when the routing provider fails.

### `GET /api/cities/?state=TX`

Lists the city names of a state (from the US Census) that the API accepts as `"City, ST"`. The planner page uses it to fill its city picker.

### `GET /` (also `/api/route/map/?start=...&finish=...`)

The web planner: state/city pickers, plus a Leaflet map (Esri basemap tiles, no key needed) with the route, numbered stops and totals. It reuses the cached route, so it makes no extra API call.

## How it works

```
"City, ST" ──offline gazetteer──▶ lat/lon ──1 ORS call (cached)──▶ route polyline
     ──KD-tree──▶ stations within 10 mi of the route + their mile marker
     ──optimizer──▶ stops, gallons, cost
```

1. **Offline geocoding.** The price list has no coordinates, so `manage.py build_geodata` ran once and geocoded each station by its city. It uses the US Census Gazetteer for places and county subdivisions, and Nominatim (rate-limited) for the ~130 small towns the Gazetteer lacks. The output is committed in `data/`. User input (`"City, ST"`) is resolved from the same table, so geocoding costs **zero API calls** per request.
2. **Routing.** One OpenRouteService `driving-car` request returns the full geometry and the road distance. Results are cached by start/finish coordinates.
3. **Stations on the route** ([`corridor.py`](fuel/services/corridor.py)):
   - The route is densified to 1-mile spacing and put in a `scipy` KD-tree, using unit-sphere coordinates so the distances are great-circle distances.
   - All stations are queried against it in one vectorised call.
   - Each station within 10 miles gets the mile marker of its closest route point.
4. **Optimisation** ([`optimizer.py`](fuel/services/optimizer.py)):
   - **Cheapest fuel (`stop_cost=0`)**: a greedy algorithm that is provably optimal on a line (the "gas station problem"). At each station, if a cheaper station is within range, buy just enough to reach it. Otherwise fill up and go to the cheapest station within range. A monotonic stack finds each station's next cheaper station in O(n).
   - **Cheapest fuel + stop penalty (default)**: the pure optimum happily stops to buy 0.4 gal to save a few cents. With NY → LA it makes 18 stops. Adding a fixed cost per stop breaks the greedy argument, so it is solved exactly by **dynamic programming** over (station, fuel level), at 1-mile resolution. The inner minimisation is a running prefix-minimum, so the DP is O(n · R) of vectorised numpy work. With `stop_cost=10`, NY → LA drops to **7 stops for +1.5% fuel cost**.
   - Both are verified against an exhaustive search on 300 random instances each (`fuel/tests/test_optimizer.py`).

## Assumptions

- The **tank starts empty**. The first station on the route counts as the departure point, and the few miles to it are paid at its price, so `total_gallons` is always the fuel for the whole trip.
- Station coordinates are the **city centroid** (the price list only has highway/exit addresses). That's why the corridor radius is 10 miles. Detour distance off the highway isn't added to the trip.
- When an OPIS station ID appears several times with different prices, the cheapest price is used. Canadian stations are excluded.
- The routing profile is passenger car (`driving-car`), and any USA destination ORS can route to (≤ 6,000 km) is supported.

## Performance

| step | cost |
|---|---|
| geocode start/finish | dict lookup |
| routing | 1 HTTP call on a cache miss, 0 on a hit (LocMem cache; switch to Redis in production) |
| station index | loaded from the DB once per process (~100 ms on the first request) |
| corridor + optimisation | ~10 ms for a 2,800-mile route |

The route geometry in the response is thinned to about one point every 0.5 mi to keep the payload small. The full geometry is still used for the computation.

## Layout

```
config/                         settings, root urls
fuel/
  models.py                     FuelStation
  views.py, serializers.py      API + map page
  services/
    geocode.py                  offline "City, ST" / "lat,lon" resolution
    ors.py                      OpenRouteService client (the only external call)
    station_index.py            stations as numpy arrays, built once
    corridor.py                 stations near the route + mile markers
    optimizer.py                greedy (cheapest) and DP (with stop cost)
    planner.py                  orchestration + response building
  management/commands/
    build_geodata.py            one-off data prep (needs internet; outputs committed)
    load_stations.py            CSV -> DB (offline)
  templates/fuel/map.html       Leaflet map
data/                           price list, gazetteer lookup, geocoded stations
```
