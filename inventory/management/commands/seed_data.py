"""
Load realistic demo data: 5 locations, 5 categories, 12 supplies, stock batches
(some low, some expiring, one expired), 2 emergency events and a few
transfers/dispatches so the audit trail isn't empty.

    python manage.py seed_data                 # data only
    python manage.py seed_data --with-users    # also demo users admin / manager / viewer
    python manage.py seed_data --reset         # wipe stock, transactions and events first

Safe to run more than once: stock is only loaded if there are no batches yet.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts import roles
from emergencies.models import EmergencyEvent, EventRequirement
from inventory import services
from inventory.models import Category, Location, StockBatch, StockTransaction, Supply

LOCATIONS = [
    # code, name, type, district
    ("DHK-CW", "Dhaka Central Warehouse", "WAREHOUSE", "Dhaka"),
    ("CTG-RD", "Chattogram Regional Depot", "DEPOT", "Chattogram"),
    ("KHL-RD", "Khulna Regional Depot", "DEPOT", "Khulna"),
    ("SYL-RD", "Sylhet Regional Depot", "DEPOT", "Sylhet"),
    ("CXB-RC", "Cox's Bazar Relief Center", "RELIEF_CENTER", "Cox's Bazar"),
]

CATEGORIES = [
    ("Water", "Drinking water and purification"),
    ("Food", "Dry rations and staple food"),
    ("Medical", "Medicine and first aid"),
    ("Shelter", "Tarpaulins, tents and blankets"),
    ("Hygiene", "Hygiene and sanitation kits"),
]

SUPPLIES = [
    # sku, name, category, unit, reorder_level, tracks_expiry
    ("WAT-001", "Drinking Water", "Water", "LITRE", 2000, True),
    ("WAT-002", "Water Purification Tablets", "Water", "PACK", 500, True),
    ("FOD-001", "Rice", "Food", "KG", 1000, True),
    ("FOD-002", "Lentils (Dal)", "Food", "KG", 400, True),
    ("FOD-003", "Dry Food Pack", "Food", "PACK", 500, True),
    ("MED-001", "First Aid Kit", "Medical", "PIECE", 100, True),
    ("MED-002", "Oral Rehydration Salts (ORS)", "Medical", "PACK", 1000, True),
    ("MED-003", "Paracetamol 500mg (strip)", "Medical", "PACK", 500, True),
    ("SHL-001", "Tarpaulin Sheet", "Shelter", "PIECE", 200, False),
    ("SHL-002", "Blanket", "Shelter", "PIECE", 300, False),
    ("SHL-003", "Family Tent", "Shelter", "PIECE", 50, False),
    ("HYG-001", "Hygiene Kit", "Hygiene", "PIECE", 150, False),
]

# location code -> list of (sku, quantity, days until expiry or None)
STOCK = {
    "DHK-CW": [
        ("WAT-001", 6000, 300), ("WAT-002", 2000, 400), ("FOD-001", 4000, 240), ("FOD-002", 1500, 200),
        ("FOD-003", 1500, 25), ("FOD-003", 1000, 150), ("MED-001", 300, 500), ("MED-002", 4000, 365),
        ("MED-003", 1500, 18), ("SHL-001", 800, None), ("SHL-002", 900, None), ("SHL-003", 150, None),
        ("HYG-001", 500, None),
    ],
    "CTG-RD": [
        ("WAT-001", 4000, 200), ("FOD-001", 2500, 180), ("FOD-002", 600, 160), ("FOD-003", 900, 90),
        ("MED-001", 200, 400), ("MED-002", 2500, 10), ("SHL-001", 400, None), ("SHL-002", 500, None),
        ("HYG-001", 250, None),
    ],
    "KHL-RD": [
        ("WAT-001", 2500, 150), ("FOD-001", 1800, 120), ("FOD-003", 300, 60), ("MED-001", 80, 300),
        ("MED-002", 900, 200), ("SHL-001", 150, None), ("SHL-002", 350, None),
    ],
    "SYL-RD": [
        ("WAT-001", 1500, 220), ("WAT-002", 300, 28), ("FOD-001", 1200, 200), ("MED-001", 60, 250),
        ("SHL-002", 200, None), ("SHL-003", 40, None),
    ],
    # The cyclone-hit relief center is short on several items.
    # Numbers match the readiness example in the proposal slides:
    # water 7,500 / 10,000 (short), rice 5,500 / 5,000 (ready),
    # first aid kits 320 / 500 (short), blankets 700 + 200 transferred = 900 / 800 (ready).
    "CXB-RC": [
        ("WAT-001", 5000, 120), ("WAT-001", 2500, 60), ("FOD-001", 3000, 90), ("FOD-001", 2500, 150),
        ("FOD-003", 200, 12), ("MED-001", 320, 180), ("MED-002", 600, 150), ("SHL-001", 120, None),
        ("SHL-002", 700, None),
    ],
}

# One already-expired batch so expiry alerts have something to show.
EXPIRED_STOCK = [("KHL-RD", "MED-003", 200, -5)]

EVENTS = [
    {
        "name": "Cyclone Response — Cox's Bazar",
        "event_type": "CYCLONE",
        "severity": "HIGH",
        "status": "ACTIVE",
        "location": "CXB-RC",
        "affected_area": "Cox's Bazar Sadar, Teknaf, Ukhia",
        "description": "Cyclone landfall expected within 48 hours. Pre-positioning relief supplies.",
        "requirements": [
            ("WAT-001", 10000, 1), ("FOD-001", 5000, 1), ("MED-001", 500, 1), ("SHL-002", 800, 2),
            ("MED-002", 3000, 1), ("SHL-001", 600, 2), ("FOD-003", 2000, 2), ("HYG-001", 300, 3),
        ],
    },
    {
        "name": "Flash Flood Preparedness — Sylhet",
        "event_type": "FLOOD",
        "severity": "MEDIUM",
        "status": "PLANNED",
        "location": "SYL-RD",
        "affected_area": "Sunamganj, Companiganj",
        "description": "Monsoon flash-flood preparedness stock target.",
        "requirements": [
            ("WAT-001", 4000, 1), ("WAT-002", 1000, 1), ("FOD-001", 2000, 1), ("MED-001", 150, 2),
            ("SHL-003", 100, 2),
        ],
    },
]

DEMO_USERS = [
    # username, role, is_staff (can open Django Admin), is_superuser
    ("admin", roles.ADMIN, True, True),
    ("manager", roles.MANAGER, True, False),
    ("viewer", roles.VIEWER, False, False),
]


class Command(BaseCommand):
    help = "Load demo data for ERIMS."

    def add_arguments(self, parser):
        parser.add_argument("--with-users", action="store_true", help="Create demo users admin/manager/viewer.")
        parser.add_argument("--password", default="Erims@2026", help="Password for demo users.")
        parser.add_argument("--reset", action="store_true", help="Delete stock, transactions and events first.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            StockTransaction.objects.all().delete()
            StockBatch.objects.all().delete()
            EmergencyEvent.objects.all().delete()
            self.stdout.write(self.style.WARNING("Deleted existing stock, transactions and events."))

        call_command("setup_roles", stdout=self.stdout)
        user = self._create_users(opts) if opts["with_users"] else None

        locations = {}
        for code, name, ltype, district in LOCATIONS:
            locations[code], _ = Location.objects.get_or_create(
                code=code, defaults={"name": name, "location_type": ltype, "district": district}
            )

        categories = {}
        for name, desc in CATEGORIES:
            categories[name], _ = Category.objects.get_or_create(name=name, defaults={"description": desc})

        supplies = {}
        for sku, name, cat, unit, reorder, expiry in SUPPLIES:
            supplies[sku], _ = Supply.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": categories[cat],
                    "unit": unit,
                    "reorder_level": reorder,
                    "tracks_expiry": expiry,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"{len(locations)} locations, {len(supplies)} supplies ready."))

        if StockBatch.objects.exists():
            self.stdout.write("Stock already exists — skipping stock and events (use --reset to reload).")
            return

        self._load_stock(locations, supplies, user)
        events = self._load_events(locations, supplies, user)
        self._load_sample_movements(locations, supplies, events, user)

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {StockBatch.objects.count()} batches, "
                f"{StockTransaction.objects.count()} transactions, "
                f"{EmergencyEvent.objects.count()} emergency events."
            )
        )

    # ------------------------------------------------------------------
    def _create_users(self, opts):
        User = get_user_model()
        admin_user = None
        for username, role, is_staff, is_superuser in DEMO_USERS:
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"is_staff": is_staff, "is_superuser": is_superuser, "first_name": username.title()},
            )
            if created:
                u.set_password(opts["password"])
                u.save()
            u.groups.set([Group.objects.get(name=role)])
            if username == "admin":
                admin_user = u
            state = "created" if created else "already exists"
            self.stdout.write(f"  user '{username}' ({role}) {state}")
        self.stdout.write(self.style.SUCCESS(f"Demo users ready. Password for new users: {opts['password']}"))
        return admin_user

    def _load_stock(self, locations, supplies, user):
        today = timezone.localdate()
        for code, items in STOCK.items():
            for i, (sku, qty, days) in enumerate(items, start=1):
                supply = supplies[sku]
                services.receive_stock(
                    supply=supply,
                    location=locations[code],
                    quantity=qty,
                    user=user,
                    expiry_date=today + timedelta(days=days) if days is not None else None,
                    batch_number=f"{code}-{sku}-{i:02d}",
                    reference="Opening stock",
                )

        # Expired stock can't be "received", so create it as historical opening stock.
        for code, sku, qty, days in EXPIRED_STOCK:
            batch = StockBatch.objects.create(
                supply=supplies[sku],
                location=locations[code],
                batch_number=f"{code}-{sku}-OLD",
                quantity=qty,
                expiry_date=today + timedelta(days=days),
                received_date=today - timedelta(days=365),
            )
            StockTransaction.objects.create(
                transaction_type=StockTransaction.Type.RECEIVED,
                supply=supplies[sku],
                batch=batch,
                quantity=qty,
                to_location=locations[code],
                reference="Opening stock (historical)",
                performed_by=user,
            )

    def _load_events(self, locations, supplies, user):
        events = {}
        for data in EVENTS:
            event = EmergencyEvent.objects.create(
                name=data["name"],
                event_type=data["event_type"],
                severity=data["severity"],
                status=data["status"],
                response_location=locations[data["location"]],
                affected_area=data["affected_area"],
                description=data["description"],
                created_by=user,
            )
            EventRequirement.objects.bulk_create(
                EventRequirement(event=event, supply=supplies[sku], quantity_required=qty, priority=prio)
                for sku, qty, prio in data["requirements"]
            )
            events[data["location"]] = event
        return events

    def _load_sample_movements(self, locations, supplies, events, user):
        cyclone = events["CXB-RC"]
        services.transfer_stock(
            supply=supplies["SHL-002"],
            from_location=locations["DHK-CW"],
            to_location=locations["CXB-RC"],
            quantity=200,
            user=user,
            emergency_event=cyclone,
            reference="TR-0001",
            reason="Pre-positioning blankets for cyclone response",
        )
        services.dispatch_stock(
            supply=supplies["FOD-003"],
            location=locations["CXB-RC"],
            quantity=50,
            user=user,
            emergency_event=cyclone,
            reference="DS-0001",
            reason="Distributed at Teknaf shelter",
        )
        services.write_off_stock(
            batch=StockBatch.objects.get(batch_number="CTG-RD-SHL-001-07"),
            quantity=10,
            transaction_type=StockTransaction.Type.DAMAGED,
            user=user,
            reason="Water damage in storage",
        )
