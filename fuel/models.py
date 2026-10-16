from django.db import models


class FuelStation(models.Model):
    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    price = models.DecimalField(max_digits=6, decimal_places=3, help_text="USD per gallon")
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ["price"]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.price}"
