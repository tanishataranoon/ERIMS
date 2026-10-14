"""
Emergency events and the resources each one needs.

The readiness check (Week 2) compares EventRequirement.quantity_required
with the usable stock available for each supply.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class EmergencyEvent(models.Model):
    class EventType(models.TextChoices):
        CYCLONE = "CYCLONE", "Cyclone"
        FLOOD = "FLOOD", "Flood"
        EARTHQUAKE = "EARTHQUAKE", "Earthquake"
        FIRE = "FIRE", "Fire"
        LANDSLIDE = "LANDSLIDE", "Landslide"
        OTHER = "OTHER", "Other"

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned / preparedness"
        ACTIVE = "ACTIVE", "Active"
        CLOSED = "CLOSED", "Closed"

    name = models.CharField(max_length=150)
    event_type = models.CharField(max_length=12, choices=EventType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    response_location = models.ForeignKey(
        "inventory.Location",
        on_delete=models.PROTECT,
        related_name="emergency_events",
        help_text="Where supplies must be available for this response.",
    )
    affected_area = models.CharField(max_length=200, blank=True)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "name"]

    def __str__(self):
        return self.name


class EventRequirement(models.Model):
    class Priority(models.IntegerChoices):
        HIGH = 1, "High"
        MEDIUM = 2, "Medium"
        LOW = 3, "Low"

    event = models.ForeignKey(EmergencyEvent, on_delete=models.CASCADE, related_name="requirements")
    supply = models.ForeignKey("inventory.Supply", on_delete=models.PROTECT, related_name="requirements")
    quantity_required = models.PositiveIntegerField()
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["priority", "supply__name"]
        constraints = [
            models.UniqueConstraint(fields=["event", "supply"], name="unique_supply_per_event"),
        ]

    def __str__(self):
        return f"{self.event}: {self.quantity_required} × {self.supply.name}"
