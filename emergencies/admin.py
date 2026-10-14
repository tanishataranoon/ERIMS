from django.contrib import admin

from .models import EmergencyEvent, EventRequirement


class EventRequirementInline(admin.TabularInline):
    model = EventRequirement
    extra = 1
    autocomplete_fields = ("supply",)


@admin.register(EmergencyEvent)
class EmergencyEventAdmin(admin.ModelAdmin):
    list_display = ("name", "event_type", "severity", "status", "response_location", "start_date")
    list_filter = ("event_type", "severity", "status")
    search_fields = ("name", "affected_area")
    inlines = [EventRequirementInline]

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
