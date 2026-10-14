from . import roles


def role(request):
    """Makes {{ user_role }} and role names available in every template."""
    user_role = roles.get_role(request.user) if hasattr(request, "user") else None
    return {
        "user_role": user_role,
        "is_admin_role": user_role == roles.ADMIN,
        "is_manager_role": user_role == roles.MANAGER,
    }
