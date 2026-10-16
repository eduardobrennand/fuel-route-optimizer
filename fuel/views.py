from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services.geocode import US_STATES, GeocodeError, cities_for_state
from .services.optimizer import InfeasibleRoute
from .services.ors import RouteNotFound, RoutingError
from .services.planner import SameLocationError, plan_trip, to_geojson


def _plan_or_error(data):
    serializer = RouteRequestSerializer(data=data)
    if not serializer.is_valid():
        return None, (status.HTTP_400_BAD_REQUEST, serializer.errors)
    try:
        data = serializer.validated_data
        return plan_trip(data["start"], data["finish"], data.get("stop_cost")), None
    except (GeocodeError, SameLocationError) as exc:
        return None, (status.HTTP_400_BAD_REQUEST, str(exc))
    except (InfeasibleRoute, RouteNotFound) as exc:
        return None, (status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except RoutingError as exc:
        return None, (status.HTTP_502_BAD_GATEWAY, str(exc))


class RouteView(APIView):
    def post(self, request):
        return self._respond(request, request.data)

    def get(self, request):
        return self._respond(request, request.query_params)

    def _respond(self, request, data):
        plan, error = _plan_or_error(data)
        if error:
            code, detail = error
            return Response({"error": detail}, status=code)
        query = urlencode({
            "start": plan["start"]["query"],
            "finish": plan["finish"]["query"],
            "stop_cost": plan["summary"]["stop_cost_usd"],
        })
        plan["map"] = {
            "html_url": request.build_absolute_uri(f"{reverse('route-map')}?{query}"),
            "geojson": to_geojson(plan),
        }
        del plan["route"]
        return Response(plan)


class CitiesView(APIView):
    def get(self, request):
        state = request.query_params.get("state", "").strip().upper()
        if state not in US_STATES:
            return Response({"error": "Pass ?state= with a US state code, e.g. TX."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"state": state, "cities": cities_for_state(state)})


def route_map(request):
    context = {"states": sorted(US_STATES), "stop_cost": request.GET.get("stop_cost", "")}
    if not request.GET.get("start") and not request.GET.get("finish"):
        return render(request, "fuel/map.html", context)
    plan, error = _plan_or_error(request.GET)
    if error:
        code, detail = error
        return render(request, "fuel/map.html", {**context, "error": detail}, status=code)
    return render(request, "fuel/map.html", {**context, "plan": plan, "geojson": to_geojson(plan)})
