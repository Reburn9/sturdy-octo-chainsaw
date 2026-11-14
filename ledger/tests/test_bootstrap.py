from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class BootstrapTests(TestCase):
    def test_initial_operator_is_created_without_logging_password(self):
        password = "a-private-deployment-password-95821"
        output = StringIO()
        with patch.dict(
            "os.environ",
            {"DJANGO_SUPERUSER_USERNAME": "owner", "DJANGO_SUPERUSER_PASSWORD": password},
        ):
            call_command("bootstrap_admin", stdout=output)
        user = get_user_model().objects.get(username="owner")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(password))
        self.assertNotIn(password, output.getvalue())

    def test_existing_accounts_are_never_reset_or_promoted(self):
        User = get_user_model()
        user = User.objects.create_user("owner", password="original-password")
        with patch.dict(
            "os.environ",
            {
                "DJANGO_SUPERUSER_USERNAME": "owner",
                "DJANGO_SUPERUSER_PASSWORD": "different-private-password",
            },
        ):
            with self.assertRaises(CommandError):
                call_command("bootstrap_admin", stdout=StringIO())
            user.is_superuser = user.is_staff = True
            user.save()
            call_command("bootstrap_admin", stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password("original-password"))

    def test_empty_partial_or_weak_configuration_is_safe(self):
        with patch.dict(
            "os.environ", {"DJANGO_SUPERUSER_USERNAME": "", "DJANGO_SUPERUSER_PASSWORD": ""}
        ):
            call_command("bootstrap_admin", stdout=StringIO())
        for username, password in [("owner", ""), ("owner", "123")]:
            with patch.dict(
                "os.environ",
                {"DJANGO_SUPERUSER_USERNAME": username, "DJANGO_SUPERUSER_PASSWORD": password},
            ):
                with self.assertRaises(CommandError):
                    call_command("bootstrap_admin", stdout=StringIO())
        self.assertFalse(get_user_model().objects.exists())
