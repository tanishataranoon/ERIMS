"""
Tests for the stock services. Run with:  python manage.py test
"""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from emergencies.models import EmergencyEvent
from inventory import services
from inventory.models import Category, Location, StockBatch, StockTransaction, Supply
from inventory.services import StockError

T = StockTransaction.Type


class StockServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tester", password="x")
        cls.dhaka = Location.objects.create(code="DHK", name="Dhaka", location_type="WAREHOUSE", district="Dhaka")
        cls.cxb = Location.objects.create(code="CXB", name="Cox's Bazar", location_type="RELIEF_CENTER", district="CXB")
        food = Category.objects.create(name="Food")
        shelter = Category.objects.create(name="Shelter")
        cls.rice = Supply.objects.create(sku="R1", name="Rice", category=food, unit="KG", reorder_level=100)
        cls.blanket = Supply.objects.create(
            sku="B1", name="Blanket", category=shelter, unit="PIECE", reorder_level=10, tracks_expiry=False
        )
        cls.today = timezone.localdate()

    def days(self, n):
        return self.today + timedelta(days=n)

    # --- receive -------------------------------------------------------
    def test_receive_creates_batch_and_transaction(self):
        batch = services.receive_stock(
            supply=self.rice, location=self.dhaka, quantity=500, user=self.user, expiry_date=self.days(100)
        )
        self.assertEqual(batch.quantity, 500)
        txn = StockTransaction.objects.get()
        self.assertEqual(txn.transaction_type, T.RECEIVED)
        self.assertEqual(txn.to_location, self.dhaka)
        self.assertEqual(txn.performed_by, self.user)

    def test_receiving_same_batch_twice_adds_to_it(self):
        for _ in range(2):
            services.receive_stock(
                supply=self.rice, location=self.dhaka, quantity=100, expiry_date=self.days(50), batch_number="A"
            )
        self.assertEqual(StockBatch.objects.count(), 1)
        self.assertEqual(StockBatch.objects.get().quantity, 200)
        self.assertEqual(StockTransaction.objects.count(), 2)

    def test_receive_requires_expiry_for_perishables(self):
        with self.assertRaises(StockError):
            services.receive_stock(supply=self.rice, location=self.dhaka, quantity=10)

    def test_receive_rejects_expired_stock(self):
        with self.assertRaises(StockError):
            services.receive_stock(supply=self.rice, location=self.dhaka, quantity=10, expiry_date=self.days(-1))

    def test_receive_rejects_zero_or_negative(self):
        for bad in (0, -5):
            with self.assertRaises(StockError):
                services.receive_stock(supply=self.blanket, location=self.dhaka, quantity=bad)

    # --- dispatch ------------------------------------------------------
    def test_dispatch_uses_earliest_expiry_first(self):
        late = services.receive_stock(
            supply=self.rice, location=self.dhaka, quantity=100, expiry_date=self.days(200), batch_number="LATE"
        )
        early = services.receive_stock(
            supply=self.rice, location=self.dhaka, quantity=100, expiry_date=self.days(10), batch_number="EARLY"
        )
        services.dispatch_stock(supply=self.rice, location=self.dhaka, quantity=150, user=self.user)
        early.refresh_from_db()
        late.refresh_from_db()
        self.assertEqual(early.quantity, 0)
        self.assertEqual(late.quantity, 50)
        self.assertEqual(StockTransaction.objects.filter(transaction_type=T.DISPATCHED).count(), 2)

    def test_dispatch_more_than_available_changes_nothing(self):
        batch = services.receive_stock(supply=self.blanket, location=self.dhaka, quantity=30)
        with self.assertRaises(StockError):
            services.dispatch_stock(supply=self.blanket, location=self.dhaka, quantity=31)
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 30)
        self.assertFalse(StockTransaction.objects.filter(transaction_type=T.DISPATCHED).exists())

    def test_dispatch_skips_expired_batches(self):
        StockBatch.objects.create(
            supply=self.rice, location=self.dhaka, quantity=500, expiry_date=self.days(-3)
        )
        with self.assertRaises(StockError):
            services.dispatch_stock(supply=self.rice, location=self.dhaka, quantity=1)
        self.assertEqual(services.available_quantity(self.rice, self.dhaka), 0)

    def test_dispatch_can_be_linked_to_emergency(self):
        event = EmergencyEvent.objects.create(name="Cyclone", event_type="CYCLONE", response_location=self.cxb)
        services.receive_stock(supply=self.blanket, location=self.cxb, quantity=20)
        services.dispatch_stock(supply=self.blanket, location=self.cxb, quantity=5, emergency_event=event)
        self.assertEqual(event.transactions.count(), 1)

    # --- transfer ------------------------------------------------------
    def test_transfer_moves_stock_and_keeps_expiry(self):
        expiry = self.days(60)
        services.receive_stock(
            supply=self.rice, location=self.dhaka, quantity=300, expiry_date=expiry, batch_number="X"
        )
        services.transfer_stock(
            supply=self.rice, from_location=self.dhaka, to_location=self.cxb, quantity=120, user=self.user
        )
        self.assertEqual(services.available_quantity(self.rice, self.dhaka), 180)
        self.assertEqual(services.available_quantity(self.rice, self.cxb), 120)
        dest = StockBatch.objects.get(location=self.cxb)
        self.assertEqual(dest.expiry_date, expiry)
        self.assertEqual(dest.batch_number, "X")
        txn = StockTransaction.objects.get(transaction_type=T.TRANSFERRED)
        self.assertEqual((txn.from_location, txn.to_location), (self.dhaka, self.cxb))

    def test_transfer_to_same_location_fails(self):
        services.receive_stock(supply=self.blanket, location=self.dhaka, quantity=10)
        with self.assertRaises(StockError):
            services.transfer_stock(
                supply=self.blanket, from_location=self.dhaka, to_location=self.dhaka, quantity=1
            )

    # --- adjust / write-off -------------------------------------------
    def test_adjust_records_difference(self):
        batch = services.receive_stock(supply=self.blanket, location=self.dhaka, quantity=50)
        txn = services.adjust_stock(batch=batch, new_quantity=45, user=self.user, reason="Physical count")
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 45)
        self.assertEqual(txn.quantity, 5)
        self.assertEqual(txn.from_location, self.dhaka)
        self.assertIsNone(txn.to_location)

    def test_adjust_requires_reason(self):
        batch = services.receive_stock(supply=self.blanket, location=self.dhaka, quantity=50)
        with self.assertRaises(StockError):
            services.adjust_stock(batch=batch, new_quantity=40, reason="  ")

    def test_write_off_cannot_exceed_batch(self):
        batch = services.receive_stock(supply=self.blanket, location=self.dhaka, quantity=5)
        with self.assertRaises(StockError):
            services.write_off_stock(batch=batch, quantity=6, transaction_type=T.DAMAGED)
        services.write_off_stock(batch=batch, quantity=2, transaction_type=T.DAMAGED, reason="Torn")
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 3)

    # --- queries -------------------------------------------------------
    def test_expiry_querysets(self):
        StockBatch.objects.create(supply=self.rice, location=self.dhaka, quantity=1, expiry_date=self.days(-1))
        StockBatch.objects.create(supply=self.rice, location=self.dhaka, quantity=1, expiry_date=self.days(10))
        StockBatch.objects.create(supply=self.rice, location=self.dhaka, quantity=1, expiry_date=self.days(90))
        self.assertEqual(StockBatch.objects.expired().count(), 1)
        self.assertEqual(StockBatch.objects.expiring_within(30).count(), 1)
        self.assertEqual(StockBatch.objects.usable().count(), 2)


class SeedDataTests(TestCase):
    def test_seed_runs_and_is_repeatable(self):
        call_command("seed_data", "--with-users", stdout=StringIO())
        batches = StockBatch.objects.count()
        self.assertGreater(batches, 30)
        self.assertEqual(EmergencyEvent.objects.count(), 2)
        call_command("seed_data", stdout=StringIO())  # second run must not duplicate anything
        self.assertEqual(StockBatch.objects.count(), batches)
        self.assertEqual(EmergencyEvent.objects.count(), 2)
