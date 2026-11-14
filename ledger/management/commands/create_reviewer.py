import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create an active workspace account with a generated password; no superuser privileges."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", default="", help="Optional display name.")

    def handle(self, *args, **options):
        username = options["username"]
        User = get_user_model()
        if not username or len(username) > 150 or User.objects.filter(username=username).exists():
            raise CommandError("Choose an unused username of 1–150 characters.")
        password = secrets.token_urlsafe(18)
        User.objects.create_user(
            username=username, password=password, first_name=options["name"][:150]
        )
        self.stdout.write(self.style.SUCCESS(f"Created {username}. Password: {password}"))
        self.stdout.write(
            "Share this password privately. Add the username to a dataset in Members."
        )
