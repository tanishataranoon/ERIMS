"""
The three MVP roles, implemented with Django Groups.

    Admin             — everything, including users and Django Admin
    Inventory Manager — manage supplies/locations, record stock movements, manage emergencies
    Viewer            — read-only

Run `python manage.py setup_roles` after migrating to create the groups.
Use RoleRequiredMixin / role_required in views (Week 2) to protect pages.
"""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

ADMIN = "Admin"
MANAGER = "Inventory Manager"
VIEWER = "Viewer"
ALL_ROLES = (ADMIN, MANAGER, VIEWER)

_INVENTORY_MODELS = ["location", "category", "supply", "stockbatch", "stocktransaction"]
_EMERGENCY_MODELS = ["emergencyevent", "eventrequirement"]


def _perms(app, actions, models):
    return [f"{app}.{action}_{model}" for model in models for action in actions]


ROLE_PERMISSIONS = {
    VIEWER: (
        _perms("inventory", ["view"], _INVENTORY_MODELS)
        + _perms("emergencies", ["view"], _EMERGENCY_MODELS)
    ),
    MANAGER: (
        _perms("inventory", ["view"], _INVENTORY_MODELS)
        + _perms("inventory", ["add", "change"], ["location", "category", "supply"])
        + ["inventory.record_transaction"]
        + _perms("emergencies", ["view", "add", "change", "delete"], _EMERGENCY_MODELS)
    ),
    ADMIN: (
        _perms("inventory", ["view", "add", "change", "delete"], ["location", "category", "supply"])
        + _perms("inventory", ["view"], ["stockbatch", "stocktransaction"])
        + ["inventory.record_transaction"]
        + _perms("emergencies", ["view", "add", "change", "delete"], _EMERGENCY_MODELS)
        + _perms("auth", ["view", "add", "change", "delete"], ["user"])
        + _perms("auth", ["view"], ["group"])
    ),
}


def get_role(user):
    """Return the user's role name, or None. Superusers are always Admin."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    names = set(user.groups.values_list("name", flat=True))
    for role in ALL_ROLES:  # highest role wins
        if role in names:
            return role
    return None


def has_role(user, *roles):
    return get_role(user) in roles


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """For class-based views:  allowed_roles = [ADMIN, MANAGER]"""

    allowed_roles = ALL_ROLES

    def test_func(self):
        return has_role(self.request.user, *self.allowed_roles)


def role_required(*roles):
    """For function views:  @role_required(ADMIN, MANAGER)"""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
