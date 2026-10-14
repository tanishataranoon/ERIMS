"""
Inventory data model.

Key design decisions
--------------------
* Stock is stored per BATCH (supply + location + expiry date), not as one
  number per supply. This is what makes expiry alerts and
  "first-expiry-first-out" dispatch possible.
* Stock quantities are NEVER edited directly. Every change goes through
  inventory/services.py, which also writes a StockTransaction row.
  StockTransaction is therefore the audit trail.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone


class Location(models.Model):
    class LocationType(models.TextChoices):
        WAREHOUSE = "WAREHOUSE", "Central warehouse"
        DEPOT = "DEPOT", "Regional depot"
        RELIEF_CENTER = "RELIEF_CENTER", "Relief center"

    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. DHK-CW")
    name = models.CharField(max_length=120, unique=True)
    location_type = models.CharField(max_length=20, choices=LocationType.choices)
    district = models.CharField(max_length=60)
    address = models.CharField(max_length=255, blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Supply(models.Model):
    class Unit(models.TextChoices):
        PIECE = "PIECE", "piece"
        KG = "KG", "kg"
        LITRE = "LITRE", "litre"
        PACK = "PACK", "pack"
        BOX = "BOX", "box"

    sku = models.CharField("SKU", max_length=30, unique=True, help_text="Item code, e.g. WAT-001")
    name = models.CharField(max_length=120)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="supplies")
    unit = models.CharField(max_length=10, choices=Unit.choices)
    reorder_level = models.PositiveIntegerField(
        default=0,
        help_text="Alert when stock at a location falls below this quantity.",
    )
    tracks_expiry = models.BooleanField(
        default=True,
        help_text="Tick for food, water and medicine. Untick for blankets, tents, etc.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "supplies"

    def __str__(self):
        return f"{self.name} ({self.get_unit_display()})"


class StockBatchQuerySet(models.QuerySet):
    def in_stock(self):
        return self.filter(quantity__gt=0)

    def usable(self):
        """Batches with stock that have not expired (expiry today is still usable)."""
        today = timezone.localdate()
        return self.in_stock().filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))

    def expired(self):
        return self.in_stock().filter(expiry_date__lt=timezone.localdate())

    def expiring_within(self, days):
        today = timezone.localdate()
        return self.in_stock().filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=days),
        )

    def total_quantity(self):
        return self.aggregate(total=Sum("quantity"))["total"] or 0


class StockBatch(models.Model):
    supply = models.ForeignKey(Supply, on_delete=models.PROTECT, related_name="batches")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="batches")
    batch_number = models.CharField(max_length=50, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    expiry_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StockBatchQuerySet.as_manager()

    class Meta:
        ordering = ["supply__name", "location__name", "expiry_date"]
        verbose_name_plural = "stock batches"
        indexes = [
            models.Index(fields=["supply", "location"]),
            models.Index(fields=["expiry_date"]),
        ]

    def __str__(self):
        expiry = self.expiry_date.isoformat() if self.expiry_date else "no expiry"
        return f"{self.supply.name} @ {self.location.code} — {self.quantity} ({expiry})"

    @property
    def is_expired(self):
        return self.expiry_date is not None and self.expiry_date < timezone.localdate()

    @property
    def days_to_expiry(self):
        if self.expiry_date is None:
            return None
        return (self.expiry_date - timezone.localdate()).days


class StockTransaction(models.Model):
    """One row per stock movement. Never edited or deleted — this is the audit trail."""

    class Type(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        DISPATCHED = "DISPATCHED", "Dispatched"
        TRANSFERRED = "TRANSFERRED", "Transferred"
        ADJUSTED = "ADJUSTED", "Adjusted"
        DAMAGED = "DAMAGED", "Damaged"
        EXPIRED = "EXPIRED", "Expired"

    transaction_type = models.CharField(max_length=12, choices=Type.choices)
    supply = models.ForeignKey(Supply, on_delete=models.PROTECT, related_name="transactions")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions"
    )
    quantity = models.PositiveIntegerField()
    # Stock leaves from_location and/or arrives at to_location.
    #   RECEIVED:    to_location only
    #   DISPATCHED / DAMAGED / EXPIRED: from_location only
    #   TRANSFERRED: both
    #   ADJUSTED:    to_location if increased, from_location if decreased
    from_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="outgoing_transactions"
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="incoming_transactions"
    )
    emergency_event = models.ForeignKey(
        "emergencies.EmergencyEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    reference = models.CharField(max_length=100, blank=True, help_text="Challan / PO / request number")
    reason = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_transactions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        permissions = [("record_transaction", "Can record stock transactions")]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="transaction_quantity_positive"),
            models.CheckConstraint(
                condition=Q(from_location__isnull=False) | Q(to_location__isnull=False),
                name="transaction_has_a_location",
            ),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.quantity} × {self.supply.name}"
