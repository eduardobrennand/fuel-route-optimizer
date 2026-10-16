import random

import numpy as np
import pytest

from fuel.services.optimizer import InfeasibleRoute, next_cheaper, plan_refuels, plan_refuels_with_stop_cost


def cost(purchases, prices):
    return sum(prices[b.index] * b.miles_of_fuel for b in purchases)


def brute_force_cost(positions, prices, destination, tank_range, stop_cost=0.0):
    inf = float("inf")
    stops = list(positions) + [destination]
    best = [[inf] * (tank_range + 1) for _ in stops]
    best[0][0] = 0.0
    for i in range(len(positions)):
        arrived = best[i][:]
        for f in range(tank_range + 1):
            for g in range(f + 1, tank_range + 1):
                best[i][g] = min(best[i][g], arrived[f] + stop_cost + (g - f) * prices[i])
        for j in range(i + 1, len(stops)):
            dist = stops[j] - stops[i]
            if dist > tank_range:
                break
            for f in range(dist, tank_range + 1):
                best[j][f - dist] = min(best[j][f - dist], best[i][f])
    return min(best[-1])


def test_next_cheaper():
    assert next_cheaper(np.array([3.0, 4.0, 2.0, 2.0, 1.0])).tolist() == [2, 2, 4, 4, -1]


def test_short_trip_buys_exactly_what_is_needed():
    purchases = plan_refuels([0], [3.0], destination=120, tank_range=500)
    assert len(purchases) == 1 and purchases[0].miles_of_fuel == pytest.approx(120)


def test_buys_just_enough_to_reach_cheaper_station():
    purchases = plan_refuels([0, 100], [4.0, 3.0], destination=400, tank_range=500)
    assert [(b.index, b.miles_of_fuel) for b in purchases] == [(0, 100), (1, 300)]


def test_fills_up_when_next_stations_are_more_expensive():
    purchases = plan_refuels([0, 450, 700], [3.0, 5.0, 4.0], destination=900, tank_range=500)
    assert purchases[0].index == 0 and purchases[0].miles_of_fuel == pytest.approx(500)
    assert cost(purchases, [3.0, 5.0, 4.0]) == pytest.approx(500 * 3 + 200 * 5 + 200 * 4)


def test_gap_longer_than_range_is_infeasible():
    with pytest.raises(InfeasibleRoute):
        plan_refuels([0, 600], [3.0, 3.0], destination=900, tank_range=500)


def test_requires_station_at_start():
    with pytest.raises(InfeasibleRoute):
        plan_refuels([10], [3.0], destination=100, tank_range=500)


@pytest.mark.parametrize("seed", range(300))
def test_matches_brute_force(seed):
    rng = random.Random(seed)
    tank_range = rng.randint(5, 25)
    destination = rng.randint(1, 80)
    positions = sorted({0, *(rng.randrange(1, destination) for _ in range(rng.randint(0, 12)) if destination > 1)})
    prices = [rng.choice([1.0, 2.0, 2.5, 3.0, 4.0, 5.0]) for _ in positions]
    expected = brute_force_cost(positions, prices, destination, tank_range)
    if expected == float("inf"):
        with pytest.raises(InfeasibleRoute):
            plan_refuels(positions, prices, destination, tank_range)
    else:
        purchases = plan_refuels(positions, prices, destination, tank_range)
        assert cost(purchases, prices) == pytest.approx(expected)
        assert sum(b.miles_of_fuel for b in purchases) == pytest.approx(destination)


def random_instance(seed):
    rng = random.Random(seed)
    tank_range = rng.randint(5, 25)
    destination = rng.randint(1, 80)
    positions = sorted({0, *(rng.randrange(1, destination) for _ in range(rng.randint(0, 12)) if destination > 1)})
    prices = [rng.choice([1.0, 2.0, 2.5, 3.0, 4.0, 5.0]) for _ in positions]
    return positions, prices, destination, tank_range, rng.choice([0.0, 0.5, 3.0, 10.0])


@pytest.mark.parametrize("seed", range(300))
def test_stop_cost_dp_matches_brute_force(seed):
    positions, prices, destination, tank_range, stop_cost = random_instance(seed)
    expected = brute_force_cost(positions, prices, destination, tank_range, stop_cost)
    if expected == float("inf"):
        with pytest.raises(InfeasibleRoute):
            plan_refuels_with_stop_cost(positions, prices, destination, tank_range, stop_cost)
        return
    purchases = plan_refuels_with_stop_cost(positions, prices, destination, tank_range, stop_cost)
    assert cost(purchases, prices) + stop_cost * len(purchases) == pytest.approx(expected)
    assert sum(b.miles_of_fuel for b in purchases) >= destination - 1e-9
    if stop_cost == 0:
        assert cost(purchases, prices) == pytest.approx(cost(plan_refuels(positions, prices, destination, tank_range), prices))


def test_stop_cost_removes_tiny_stops():
    positions, prices = [0, 10], [3.00, 2.99]
    assert len(plan_refuels(positions, prices, 300, 500)) == 2
    purchases = plan_refuels_with_stop_cost(positions, prices, 300, 500, stop_cost=5.0)
    assert [(b.index, b.miles_of_fuel) for b in purchases] == [(0, 300)]
