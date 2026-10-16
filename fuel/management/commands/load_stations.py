import csv
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from fuel.models import FuelStation


class Command(BaseCommand):
    help = "Load the geocoded fuel stations (data/stations_geocoded.csv) into the database. Idempotent, offline."

    def handle(self, *args, **options):
        with open(settings.DATA_DIR / "stations_geocoded.csv", newline="", encoding="utf-8") as f:
            stations = [
                FuelStation(
                    opis_id=int(r["opis_id"]),
                    name=r["name"],
                    address=r["address"],
                    city=r["city"],
                    state=r["state"],
                    price=Decimal(r["price"]).quantize(Decimal("0.001")),
                    latitude=float(r["lat"]),
                    longitude=float(r["lon"]),
                )
                for r in csv.DictReader(f)
            ]
        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(stations)} fuel stations."))
