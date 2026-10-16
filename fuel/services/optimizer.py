from bisect import bisect_right
from dataclasses import dataclass

import numpy as np


class InfeasibleRoute(Exception):
    pass


@dataclass(frozen=True)
class Purchase:
    index: int
    miles_of_fuel: float


def next_cheaper(prices: np.ndarray) -> np.ndarray:
    result = np.full(len(prices), -1, dtype=np.int64)
    stack: list[int] = []
    for j, price in enumerate(prices):
        while stack and price < prices[stack[-1]]:
            result[stack.pop()] = j
        stack.append(j)
    return result


def plan_refuels(positions, prices, destination: float, tank_range: float) -> list[Purchase]:
    x = np.asarray(positions, dtype=float)
    p = np.asarray(prices, dtype=float)
    if destination <= 0:
        return []
    if len(x) == 0 or x[0] != 0:
        raise InfeasibleRoute("The vehicle starts empty but there is no fuel station at the start.")

    cheaper = next_cheaper(p)
    purchases: list[Purchase] = []
    i, fuel = 0, 0.0

    while True:
        j = cheaper[i]
        if j != -1 and x[j] - x[i] <= tank_range:
            need = x[j] - x[i]
            target, next_i = need, j
        elif destination - x[i] <= tank_range:
            target, next_i = destination - x[i], None
        else:
            hi = bisect_right(x, x[i] + tank_range)
            if hi <= i + 1:
                raise InfeasibleRoute(
                    f"No fuel station within {tank_range:.0f} miles after mile {x[i]:.0f}; the route cannot be completed."
                )
            window = p[i + 1 : hi]
            k = i + 1 + (len(window) - 1 - int(np.argmin(window[::-1])))
            target, next_i = tank_range, k

        if target > fuel + 1e-9:
            purchases.append(Purchase(index=i, miles_of_fuel=target - fuel))
            fuel = target
        if next_i is None:
            return purchases
        fuel -= x[next_i] - x[i]
        i = next_i


def plan_refuels_with_stop_cost(
    positions, prices, destination: float, tank_range: float, stop_cost: float, resolution: float = 1.0
) -> list[Purchase]:
    x = np.asarray(positions, dtype=float)
    p = np.asarray(prices, dtype=float) * resolution
    if destination <= 0:
        return []
    if len(x) == 0 or x[0] != 0:
        raise InfeasibleRoute("The vehicle starts empty but there is no fuel station at the start.")

    cap = int(round(tank_range / resolution))
    units = np.round(np.append(x, destination) / resolution).astype(np.int64)
    gaps = np.diff(units)
    levels = np.arange(cap + 1)

    arrive = np.full(cap + 1, np.inf)
    arrive[0] = 0.0
    sources = np.empty((len(x), cap + 1), dtype=np.int32)

    for k in range(len(x)):
        reduced = arrive - p[k] * levels
        running_min = np.minimum.accumulate(reduced)
        argmin = np.maximum.accumulate(np.where(reduced <= running_min, levels, 0))
        buy = stop_cost + p[k] * levels + running_min
        bought = buy < arrive
        after = np.where(bought, buy, arrive)
        sources[k] = np.where(bought, argmin, levels)

        gap = gaps[k]
        if gap > cap or not np.isfinite(after[gap:]).any():
            raise InfeasibleRoute(
                f"No fuel station within {tank_range:.0f} miles after mile {x[k]:.0f}; the route cannot be completed."
            )
        if k == len(x) - 1:
            level = gap + int(np.argmin(after[gap:]))
            break
        arrive = np.full(cap + 1, np.inf)
        arrive[: cap + 1 - gap] = after[gap:]

    purchases: list[Purchase] = []
    for k in range(len(x) - 1, -1, -1):
        source = int(sources[k][level])
        if source != level:
            purchases.append(Purchase(index=k, miles_of_fuel=(level - source) * resolution))
        if k:
            level = source + int(gaps[k - 1])
    return purchases[::-1]
