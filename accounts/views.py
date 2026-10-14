from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from emergencies.models import EmergencyEvent
from inventory.models import Location, StockBatch, StockTransaction, Supply


@login_required
def home(request):
    """Week 1 landing page: proves login, roles and the database all work.
    Replaced by the real dashboard in Week 3."""
    context = {
        "location_count": Location.objects.filter(is_active=True).count(),
        "supply_count": Supply.objects.filter(is_active=True).count(),
        "batch_count": StockBatch.objects.in_stock().count(),
        "active_event_count": EmergencyEvent.objects.filter(status=EmergencyEvent.Status.ACTIVE).count(),
        "recent_transactions": StockTransaction.objects.select_related(
            "supply", "from_location", "to_location", "performed_by"
        )[:10],
    }
    return render(request, "home.html", context)
