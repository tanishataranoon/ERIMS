"""
Stock services — the ONLY place where stock quantities change.

Every function:
  * runs inside a database transaction (all-or-nothing),
  * locks the batch rows it touches (select_for_update) so two users
    can't dispatch the same stock at the same time,
  * refuses to let stock go negative,
  * writes StockTransaction rows (the audit trail).

Views, forms, management commands and tests should call these functions
instead of changing StockBatch.quantity directly.
"""
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import StockBatch, StockTransaction

T = StockTransaction.Type


class StockError(Exception):
    """Raised when a stock operation is not allowed (e.g. not enough stock)."""


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------
def available_quantity(supply, location=None):
    """Usable (non-expired) quantity of a supply, at one location or everywhere."""
    qs = StockBatch.objects.usable().filter(supply=supply)
    if location is not None:
        qs = qs.filter(location=location)
    return qs.total_quantity()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _check_quantity(quantity):
    if not isinstance(quantity, int) or quantity <= 0:
        raise StockError("Quantity must be a whole number greater than zero.")


def _locked_batch(*, supply, location, batch_number, expiry_date):
    """Find (and lock) a batch with the same supply/location/batch/expiry, or create it."""
    batch = (
        StockBatch.objects.select_for_update()
        .filter(supply=supply, location=location, batch_number=batch_number, expiry_date=expiry_date)
        .order_by("id")
        .first()
    )
    if batch is None:
        batch = StockBatch.objects.create(
            supply=supply,
            location=location,
            batch_number=batch_number,
            expiry_date=expiry_date,
            quantity=0,
        )
    return batch


def _allocate_fefo(supply, location, quantity):
    """
    Pick batches First-Expiry-First-Out and lock them.
    Returns a list of (batch, quantity_to_take). Expired batches are skipped.
    """
    today = timezone.localdate()
    batches = list(
        StockBatch.objects.select_for_update()
        .filter(supply=supply, location=location, quantity__gt=0)
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
        .order_by(F("expiry_date").asc(nulls_last=True), "received_date", "id")
    )
    available = sum(b.quantity for b in batches)
    if available < quantity:
        raise StockError(
            f"Not enough usable {supply.name} at {location.name}: "
            f"requested {quantity}, available {available}."
        )

    allocations, remaining = [], quantity
    for batch in batches:
        if remaining == 0:
            break
        take = min(batch.quantity, remaining)
        allocations.append((batch, take))
        remaining -= take
    return allocations


def _decrease(batch, amount):
    batch.quantity -= amount
    batch.save(update_fields=["quantity", "updated_at"])


def _increase(batch, amount):
    batch.quantity += amount
    batch.save(update_fields=["quantity", "updated_at"])


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------
@transaction.atomic
def receive_stock(
    *, supply, location, quantity, user=None, expiry_date=None, batch_number="", reference="", reason=""
):
    """New stock arrives at a location (donation, purchase, delivery)."""
    _check_quantity(quantity)
    if supply.tracks_expiry and expiry_date is None:
        raise StockError(f"{supply.name} tracks expiry — an expiry date is required.")
    if not supply.tracks_expiry:
        expiry_date = None
    if expiry_date is not None and expiry_date < timezone.localdate():
        raise StockError("Cannot receive stock that has already expired.")

    batch = _locked_batch(supply=supply, location=location, batch_number=batch_number, expiry_date=expiry_date)
    _increase(batch, quantity)
    StockTransaction.objects.create(
        transaction_type=T.RECEIVED,
        supply=supply,
        batch=batch,
        quantity=quantity,
        to_location=location,
        reference=reference,
        reason=reason,
        performed_by=user,
    )
    return batch


@transaction.atomic
def dispatch_stock(*, supply, location, quantity, user=None, emergency_event=None, reference="", reason=""):
    """Stock leaves the system to beneficiaries. Uses earliest-expiring batches first."""
    _check_quantity(quantity)
    records = []
    for batch, take in _allocate_fefo(supply, location, quantity):
        _decrease(batch, take)
        records.append(
            StockTransaction.objects.create(
                transaction_type=T.DISPATCHED,
                supply=supply,
                batch=batch,
                quantity=take,
                from_location=location,
                emergency_event=emergency_event,
                reference=reference,
                reason=reason,
                performed_by=user,
            )
        )
    return records


@transaction.atomic
def transfer_stock(
    *, supply, from_location, to_location, quantity, user=None, emergency_event=None, reference="", reason=""
):
    """Move stock between two locations. Batch number and expiry date travel with the stock."""
    _check_quantity(quantity)
    if from_location.pk == to_location.pk:
        raise StockError("Source and destination must be different locations.")

    records = []
    for source, take in _allocate_fefo(supply, from_location, quantity):
        _decrease(source, take)
        destination = _locked_batch(
            supply=supply,
            location=to_location,
            batch_number=source.batch_number,
            expiry_date=source.expiry_date,
        )
        _increase(destination, take)
        records.append(
            StockTransaction.objects.create(
                transaction_type=T.TRANSFERRED,
                supply=supply,
                batch=destination,
                quantity=take,
                from_location=from_location,
                to_location=to_location,
                emergency_event=emergency_event,
                reference=reference,
                reason=reason,
                performed_by=user,
            )
        )
    return records


@transaction.atomic
def adjust_stock(*, batch, new_quantity, user=None, reason):
    """Correct a batch after a physical count. A reason is mandatory."""
    if not reason or not reason.strip():
        raise StockError("A reason is required for stock adjustments.")
    if not isinstance(new_quantity, int) or new_quantity < 0:
        raise StockError("New quantity must be zero or a positive whole number.")

    batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
    delta = new_quantity - batch.quantity
    if delta == 0:
        raise StockError("New quantity is the same as the current quantity — nothing to adjust.")

    batch.quantity = new_quantity
    batch.save(update_fields=["quantity", "updated_at"])
    return StockTransaction.objects.create(
        transaction_type=T.ADJUSTED,
        supply=batch.supply,
        batch=batch,
        quantity=abs(delta),
        to_location=batch.location if delta > 0 else None,
        from_location=batch.location if delta < 0 else None,
        reason=reason,
        performed_by=user,
    )


@transaction.atomic
def write_off_stock(*, batch, quantity, transaction_type, user=None, reason=""):
    """Remove damaged or expired stock from a specific batch."""
    if transaction_type not in (T.DAMAGED, T.EXPIRED):
        raise StockError("Write-off type must be DAMAGED or EXPIRED.")
    _check_quantity(quantity)

    batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
    if quantity > batch.quantity:
        raise StockError(f"Batch only has {batch.quantity}; cannot write off {quantity}.")

    _decrease(batch, quantity)
    return StockTransaction.objects.create(
        transaction_type=transaction_type,
        supply=batch.supply,
        batch=batch,
        quantity=quantity,
        from_location=batch.location,
        reason=reason,
        performed_by=user,
    )
