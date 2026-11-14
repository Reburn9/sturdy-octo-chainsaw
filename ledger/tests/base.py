import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from ledger import services
from ledger.models import Assignment, Membership


class WorkspaceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.manager = User.objects.create_user("manager", password="test-password-123")
        cls.reviewer = User.objects.create_user("reviewer", password="test-password-123")
        cls.second = User.objects.create_user("second", password="test-password-123")
        cls.viewer = User.objects.create_user("viewer", password="test-password-123")
        cls.outsider = User.objects.create_user("outsider", password="test-password-123")
        cls.dataset = services.create_dataset(
            cls.manager,
            name="Feedback",
            description="Sentiment",
            labels=["positive", "neutral", "negative"],
        )
        for user, role in [
            (cls.reviewer, Membership.Role.REVIEWER),
            (cls.second, Membership.Role.REVIEWER),
            (cls.viewer, Membership.Role.VIEWER),
        ]:
            Membership.objects.create(dataset=cls.dataset, user=user, role=role)
        services.import_records(
            cls.dataset,
            cls.manager,
            b"id,text\none,A useful new feature\ntwo,The old export is broken\n",
            "data.csv",
        )
        cls.record = cls.dataset.records.get(external_id="one")
        for user in [cls.reviewer, cls.second]:
            Assignment.objects.create(record=cls.record, reviewer=user, assigned_by=cls.manager)

    def vote(self, user, label="positive", record=None):
        record = record or self.record
        record.refresh_from_db()
        return services.submit_review(
            record, user, label=label, comment="Evidence in the text.", version=record.version
        )

    def payload(self, **changes):
        data = {
            "label": "positive",
            "comment": "A clear improvement.",
            "version": self.record.version,
        }
        data.update(changes)
        return json.dumps(data)
