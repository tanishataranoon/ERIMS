from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts import roles


class RoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", stdout=StringIO())
        User = get_user_model()
        cls.viewer = User.objects.create_user("v", password="pass12345")
        cls.viewer.groups.add(Group.objects.get(name=roles.VIEWER))
        cls.manager = User.objects.create_user("m", password="pass12345")
        cls.manager.groups.add(Group.objects.get(name=roles.MANAGER))
        cls.nobody = User.objects.create_user("n", password="pass12345")
        cls.superuser = User.objects.create_superuser("s", password="pass12345")

    def test_groups_created(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), set(roles.ALL_ROLES))

    def test_setup_roles_is_repeatable(self):
        call_command("setup_roles", stdout=StringIO())
        self.assertEqual(Group.objects.count(), 3)

    def test_get_role(self):
        self.assertEqual(roles.get_role(self.viewer), roles.VIEWER)
        self.assertEqual(roles.get_role(self.manager), roles.MANAGER)
        self.assertEqual(roles.get_role(self.superuser), roles.ADMIN)
        self.assertIsNone(roles.get_role(self.nobody))

    def test_permissions(self):
        self.assertTrue(self.viewer.has_perm("inventory.view_supply"))
        self.assertFalse(self.viewer.has_perm("inventory.record_transaction"))
        self.assertTrue(self.manager.has_perm("inventory.record_transaction"))
        self.assertTrue(self.manager.has_perm("emergencies.add_emergencyevent"))
        self.assertFalse(self.manager.has_perm("auth.add_user"))


class HomePageTests(TestCase):
    def test_home_requires_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_home_loads_for_logged_in_user(self):
        get_user_model().objects.create_user("u", password="pass12345")
        self.client.login(username="u", password="pass12345")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ERIMS")

    def test_login_page_loads(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
