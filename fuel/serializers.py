from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text="'City, ST' (e.g. 'Chicago, IL') or 'lat,lon'")
    finish = serializers.CharField(max_length=200, help_text="'City, ST' (e.g. 'Denver, CO') or 'lat,lon'")
    stop_cost = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=1000,
        help_text="Penalty in USD per fuel stop (default from settings). 0 = cheapest fuel regardless of stops.",
    )
