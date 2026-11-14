import json
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ledger import services
from ledger.models import Membership

FEEDBACK = [
    ("The new search finds exactly what I need in seconds.", "positive", "positive"),
    ("My export keeps failing after I select more than one month.", "negative", "negative"),
    ("The weekly report is available in the settings menu.", "neutral", "neutral"),
    ("Our onboarding took half the time with the new checklist.", "positive", "positive"),
    ("The app logs me out every time I switch tabs.", "negative", "negative"),
    ("There are three subscription plans listed on the pricing page.", "neutral", "neutral"),
    ("Finally, keyboard navigation that works throughout the dashboard.", "positive", "positive"),
    ("I lost an hour of edits when the connection dropped.", "negative", "negative"),
    ("The help article was updated this morning.", "neutral", "neutral"),
    ("The support team solved my issue on the first reply.", "positive", "positive"),
    ("Notifications arrive hours after the event happened.", "negative", "negative"),
    ("The mobile layout shows the same data as the desktop view.", "neutral", "neutral"),
    ("Setup was easy, although notifications are a little late.", "positive", "neutral"),
    ("The redesign looks great but moved my most-used button.", "positive", "negative"),
    ("It does what it says; I expected more for this price.", "neutral", "negative"),
    ("Not bad at all once you figure out the confusing menu.", "positive", "neutral"),
    ("I appreciate the update, even if it doesn't fix my main issue.", "positive", "negative"),
    ("The sync works eventually, which is better than before.", "neutral", "negative"),
    ("I would recommend the team workspace to other small studios.", "positive", "positive"),
    ("The billing page charged me twice for the same month.", "negative", "negative"),
    ("The latest release adds two optional notification settings.", "neutral", "neutral"),
    ("I can now find all my saved filters in one place.", "positive", "positive"),
    ("The date selector resets whenever I reopen the report.", "negative", "negative"),
    ("An account owner can invite members by email.", "neutral", "neutral"),
    ("The activity timeline is a real improvement for our workflow.", "positive", "positive"),
    ("Uploading the file hangs without showing an error.", "negative", "negative"),
    ("There is a dark theme in the appearance settings.", "neutral", "neutral"),
    ("Thank you for making the empty states so clear.", "positive", "positive"),
    ("The search results never include recently created documents.", "negative", "negative"),
    ("A CSV download includes the current set of columns.", "neutral", "neutral"),
    ("The accessible color palette makes this easier to use.", "positive", "positive"),
    ("My dashboard shows an error instead of this week's totals.", "negative", "negative"),
    ("The team name appears at the top of the workspace.", "neutral", "neutral"),
    ("Everything feels faster since the last update.", "positive", "positive"),
    ("I cannot remove an old payment method from my account.", "negative", "negative"),
    ("The invitation link remains active for seven days.", "neutral", "neutral"),
]
SUPPORT = [
    ("The download button returns a blank page.", "bug", "bug"),
    ("Can I filter the report by workspace?", "question", "question"),
    ("Please add an option to schedule weekly exports.", "feature_request", "feature_request"),
    ("I get an error when saving a custom view.", "bug", "bug"),
    ("Where do I change the team's time zone?", "question", "question"),
    ("A keyboard shortcut for search would be useful.", "feature_request", "feature_request"),
    ("Why can't I export more than a thousand rows?", "question", "bug"),
    ("Could the notification panel stop hiding my filters?", "feature_request", "bug"),
    ("A member's avatar is missing after an invitation.", "bug", "bug"),
    ("How long do you keep deleted files?", "question", "question"),
    ("It would help to pin a workspace to the sidebar.", "feature_request", "feature_request"),
    ("The account selector crashes on my phone.", "bug", "bug"),
    ("Is there a limit to custom roles?", "question", "question"),
    ("Please support CSV files with semicolon separators.", "feature_request", "feature_request"),
    ("My saved view disappears after a refresh.", "bug", "bug"),
    ("Can I change the owner of an existing report?", "question", "question"),
    ("Please let me compare two reporting periods.", "feature_request", "feature_request"),
    ("The timeline shows the same event twice.", "bug", "bug"),
]


class Command(BaseCommand):
    help = "Create clearly marked synthetic datasets and three demo accounts. Never resets existing users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", help="Optional password for local automated testing only."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(username__in=["demo", "maya", "ellis"]).exists():
            raise CommandError(
                "Demo usernames already exist. Nothing was changed; use a fresh database to reseed."
            )
        password = options["password"] or secrets.token_urlsafe(18)
        if len(password) < 12:
            raise CommandError("Use a demo password of at least 12 characters.")
        manager = User.objects.create_user("demo", password=password, first_name="Demo Manager")
        maya = User.objects.create_user("maya", password=password, first_name="Maya")
        ellis = User.objects.create_user("ellis", password=password, first_name="Ellis")
        for name, description, examples, labels, complete, singles in [
            (
                "Product feedback · sentiment",
                "Synthetic demo: classify the overall sentiment in product feedback. Mixed feedback is intentionally included for adjudication.",
                FEEDBACK,
                ["positive", "neutral", "negative"],
                18,
                6,
            ),
            (
                "Support inbox · intent",
                "Synthetic demo: distinguish bugs, questions, and feature requests. Review the user's primary intent.",
                SUPPORT,
                ["bug", "question", "feature_request"],
                8,
                2,
            ),
        ]:
            dataset = services.create_dataset(
                manager, name=name, description=description, labels=labels
            )
            for reviewer in [maya, ellis]:
                services.add_member(dataset, manager, reviewer.username, Membership.Role.REVIEWER)
            payload = "\n".join(
                json.dumps(
                    {
                        "id": f"REC-{i + 1:03}",
                        "text": row[0],
                        "metadata": {
                            "source": "synthetic-demo",
                            "channel": ["in-app", "email", "survey"][i % 3],
                        },
                    }
                )
                for i, row in enumerate(examples)
            ).encode()
            services.import_records(dataset, manager, payload, "synthetic-demo.jsonl")
            services.assign_records(dataset, manager, maya.pk, len(examples))
            services.assign_records(dataset, manager, ellis.pk, len(examples) - 6)
            services.assign_records(dataset, manager, manager.pk, 6)
            for i, record in enumerate(dataset.records.all()):
                if i < complete + singles:
                    services.submit_review(
                        record,
                        maya,
                        label=examples[i][1],
                        comment="Labeled from the primary meaning of the text.",
                        version=record.version,
                    )
                if i < complete:
                    record.refresh_from_db()
                    services.submit_review(
                        record,
                        ellis,
                        label=examples[i][2],
                        comment="Reviewed independently using the dataset description.",
                        version=record.version,
                    )
                if dataset.name.startswith("Product") and i in [12, 13]:
                    record.refresh_from_db()
                    services.resolve_dispute(
                        record,
                        manager,
                        label="neutral",
                        comment="Both praise and criticism are substantive; use the mixed-feedback guideline.",
                        version=record.version,
                    )
        self.stdout.write(
            self.style.SUCCESS(
                "Created two synthetic datasets and accounts: demo (manager), maya, ellis (reviewers)."
            )
        )
        self.stdout.write(f"Local demo password for all three accounts: {password}")
        self.stdout.write(
            "All activity timestamps reflect this seed run. Do not expose demo accounts publicly."
        )
