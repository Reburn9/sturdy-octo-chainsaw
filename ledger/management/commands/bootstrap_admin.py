import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create an initial operator from private environment values. Never resets an existing account."

    @transaction.atomic
    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        if not username and not password:
            self.stdout.write("No administrator bootstrap configured; skipped.")
            return
        if not username or not password:
            raise CommandError(
                "Set both DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD privately."
            )
        User = get_user_model()
        existing = User.objects.filter(username=username).first()
        if existing:
            if not existing.is_superuser or not existing.is_active:
                raise CommandError(
                    "The bootstrap username belongs to a non-operator or inactive account. Nothing was changed."
                )
            self.stdout.write("Administrator already exists; credentials were not changed.")
            return
        user = User(username=username, is_superuser=True, is_staff=True, is_active=True)
        try:
            user.full_clean(exclude=["password"])
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(
                "Administrator settings failed validation: " + "; ".join(exc.messages)
            ) from exc
        User.objects.create_superuser(username=username, password=password, email="")
        self.stdout.write(
            "Initial administrator created. Password is available only in the private environment settings."
        )
