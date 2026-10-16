import threading
from dataclasses import dataclass

import numpy as np

from fuel.models import FuelStation

from .geo import to_unit_xyz


@dataclass(frozen=True)
class StationIndex:
    ids: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray
    xyz: np.ndarray
    info: list[dict]

    def __len__(self):
        return len(self.ids)


_index: StationIndex | None = None
_lock = threading.Lock()


def get_station_index() -> StationIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _build()
    return _index


def reset_station_index() -> None:
    global _index
    _index = None


def _build() -> StationIndex:
    rows = list(
        FuelStation.objects.order_by("pk").values_list(
            "pk", "opis_id", "name", "address", "city", "state", "price", "latitude", "longitude"
        )
    )
    lat = np.array([r[7] for r in rows], dtype=float)
    lon = np.array([r[8] for r in rows], dtype=float)
    return StationIndex(
        ids=np.array([r[0] for r in rows], dtype=np.int64),
        lat=lat,
        lon=lon,
        price=np.array([float(r[6]) for r in rows], dtype=float),
        xyz=to_unit_xyz(lat, lon) if rows else np.empty((0, 3)),
        info=[
            {"opis_id": r[1], "name": r[2], "address": r[3], "city": r[4], "state": r[5]}
            for r in rows
        ],
    )
