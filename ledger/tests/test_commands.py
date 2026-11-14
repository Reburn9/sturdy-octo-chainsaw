from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from ledger.models import Dataset


class CommandTests(TestCase):
    def test_demo_is_synthetic_and_never_resets_existing_accounts(self):
        output = StringIO()
        call_command("seed_demo", password="a-local-test-password", stdout=output)
        self.assertEqual(Dataset.objects.count(), 2)
        self.assertEqual(sum(dataset.records.count() for dataset in Dataset.objects.all()), 54)
        self.assertIn("synthetic", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        self.assertTrue(
            get_user_model().objects.get(username="demo").check_password("a-local-test-password")
        )

    def test_create_reviewer_generates_a_non_superuser_account(self):
        call_command("create_reviewer", "new-reviewer", name="New Reviewer", stdout=StringIO())
        user = get_user_model().objects.get(username="new-reviewer")
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.has_usable_password())
        with self.assertRaises(CommandError):
            call_command("create_reviewer", "new-reviewer", stdout=StringIO())
