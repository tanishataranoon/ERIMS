from django.contrib import admin

from .models import Category, Location, StockBatch, StockTransaction, Supply


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "location_type", "district", "is_active")
    list_filter = ("location_type", "district", "is_active")
    search_fields = ("code", "name", "district")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "unit", "reorder_level", "tracks_expiry", "is_active")
    list_filter = ("category", "unit", "tracks_expiry", "is_active")
    search_fields = ("sku", "name")


class ReadOnlyAdmin(admin.ModelAdmin):
    """Stock rows are changed only through inventory/services.py so every change is audited."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockBatch)
class StockBatchAdmin(ReadOnlyAdmin):
    list_display = ("supply", "location", "batch_number", "quantity", "expiry_date", "received_date")
    list_filter = ("location", "supply__category", "expiry_date")
    search_fields = ("supply__name", "supply__sku", "batch_number")
    list_select_related = ("supply", "location")


@admin.register(StockTransaction)
class StockTransactionAdmin(ReadOnlyAdmin):
    list_display = (
        "created_at",
        "transaction_type",
        "supply",
        "quantity",
        "from_location",
        "to_location",
        "emergency_event",
        "performed_by",
    )
    list_filter = ("transaction_type", "from_location", "to_location", "created_at")
    search_fields = ("supply__name", "reference", "reason")
    date_hierarchy = "created_at"
    list_select_related = ("supply", "from_location", "to_location", "emergency_event", "performed_by")
