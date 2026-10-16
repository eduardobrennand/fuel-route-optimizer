from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .geo import chord_to_miles, haversine_miles, miles_to_chord, to_unit_xyz
from .station_index import StationIndex

DENSIFY_STEP_MILES = 1.0


@dataclass(frozen=True)
class Corridor:
    station_rows: np.ndarray
    mile_markers: np.ndarray
    offsets: np.ndarray


def cumulative_miles(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    seg = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    return np.concatenate(([0.0], np.cumsum(seg)))


def thin(coordinates_lonlat, every_miles: float = 0.5) -> list[list[float]]:
    coords = np.asarray(coordinates_lonlat, dtype=float)
    if len(coords) < 3:
        return coords.round(5).tolist()
    bucket = np.floor(cumulative_miles(coords[:, 1], coords[:, 0]) / every_miles)
    keep = np.flatnonzero(np.diff(bucket, prepend=-1) > 0)
    keep = np.union1d(keep, [len(coords) - 1])
    return coords[keep].round(5).tolist()


def densify(lat: np.ndarray, lon: np.ndarray, step: float = DENSIFY_STEP_MILES):
    cum = cumulative_miles(lat, lon)
    seg = np.diff(cum)
    pieces = np.maximum(1, np.ceil(seg / step).astype(np.int64))
    seg_idx = np.repeat(np.arange(len(seg)), pieces)
    starts = np.repeat(np.cumsum(pieces) - pieces, pieces)
    frac = (np.arange(len(seg_idx)) - starts) / np.repeat(pieces, pieces)
    new_lat = np.append(lat[seg_idx] + frac * (lat[seg_idx + 1] - lat[seg_idx]), lat[-1])
    new_lon = np.append(lon[seg_idx] + frac * (lon[seg_idx + 1] - lon[seg_idx]), lon[-1])
    new_cum = np.append(cum[seg_idx] + frac * seg[seg_idx], cum[-1])
    return new_lat, new_lon, new_cum


def find_corridor(coordinates_lonlat, stations: StationIndex, radius_miles: float, route_miles: float | None = None) -> Corridor:
    coords = np.asarray(coordinates_lonlat, dtype=float)
    lat, lon, cum = densify(coords[:, 1], coords[:, 0])
    if route_miles and cum[-1] > 0:
        cum = cum * (route_miles / cum[-1])

    pad = radius_miles / 69.0 + 0.5
    in_box = np.flatnonzero(
        (stations.lat >= lat.min() - pad) & (stations.lat <= lat.max() + pad)
        & (stations.lon >= lon.min() - pad * 2) & (stations.lon <= lon.max() + pad * 2)
    )
    if len(in_box) == 0:
        return Corridor(np.empty(0, np.int64), np.empty(0), np.empty(0))

    tree = cKDTree(to_unit_xyz(lat, lon))
    dist, nearest = tree.query(stations.xyz[in_box], distance_upper_bound=miles_to_chord(radius_miles))
    hit = np.isfinite(dist)
    rows, nearest, dist = in_box[hit], nearest[hit], dist[hit]

    miles = cum[nearest]
    order = np.lexsort((stations.price[rows], miles))
    return Corridor(station_rows=rows[order], mile_markers=miles[order], offsets=chord_to_miles(dist[order]))
