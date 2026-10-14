from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

from accounts.roles import ROLE_PERMISSIONS


class Command(BaseCommand):
    help = "Create the ERIMS role groups (Admin, Inventory Manager, Viewer) and assign their permissions."

    def handle(self, *args, **options):
        for role, perm_names in ROLE_PERMISSIONS.items():
            permissions = []
            for full_name in perm_names:
                app_label, codename = full_name.split(".", 1)
                try:
                    permissions.append(
                        Permission.objects.get(content_type__app_label=app_label, codename=codename)
                    )
                except Permission.DoesNotExist as exc:
                    raise CommandError(
                        f"Permission '{full_name}' not found. Did you run 'python manage.py migrate' first?"
                    ) from exc

            group, created = Group.objects.get_or_create(name=role)
            group.permissions.set(permissions)
            verb = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{verb} role '{role}' with {len(permissions)} permissions"))
