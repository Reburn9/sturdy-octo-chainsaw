from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from ledger import services
from ledger.models import AuditEvent, Membership, Review

from .base import WorkspaceTestCase


class WorkflowTests(WorkspaceTestCase):
    def test_agreement_needs_distinct_reviewers(self):
        self.vote(self.reviewer)
        self.assertEqual(self.record.state, "in_review")
        self.vote(self.reviewer, "negative")
        self.assertEqual(self.record.reviews.count(), 1)
        self.assertIsNone(self.record.decision)
        self.vote(self.second, "negative")
        self.record.refresh_from_db()
        self.assertEqual(self.record.state, "agreed")
        self.assertEqual(self.record.decision, "negative")

    def test_stale_version_cannot_overwrite_a_vote_or_add_audit(self):
        version = self.record.version
        self.vote(self.reviewer)
        before = self.dataset.events.count()
        with self.assertRaisesMessage(services.WorkflowError, "changed") as caught:
            services.submit_review(
                self.record, self.second, label="negative", comment="", version=version
            )
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.record.reviews.count(), 1)
        self.assertEqual(self.dataset.events.count(), before)

    def test_resolution_preserves_votes_and_locks_record(self):
        self.vote(self.reviewer, "positive")
        self.vote(self.second, "negative")
        services.resolve_dispute(
            self.record,
            self.manager,
            label="neutral",
            comment="Mixed evidence.",
            version=self.record.version,
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.state, "resolved")
        self.assertEqual(self.record.decision, "neutral")
        self.assertCountEqual(
            list(self.record.reviews.values_list("label", flat=True)), ["positive", "negative"]
        )
        with self.assertRaises(services.WorkflowError):
            self.vote(self.reviewer, "neutral")

    def test_early_or_unexplained_adjudication_is_rejected(self):
        self.vote(self.reviewer)
        version = self.record.version
        with self.assertRaisesMessage(services.WorkflowError, "complete set"):
            services.resolve_dispute(
                self.record,
                self.manager,
                label="positive",
                comment="Looks positive",
                version=version,
            )
        self.record.refresh_from_db()
        self.assertEqual(self.record.version, version)
        with self.assertRaisesMessage(services.WorkflowError, "Explain"):
            services.resolve_dispute(
                self.record, self.manager, label="positive", comment="  ", version=version
            )

    def test_assignment_and_role_are_required(self):
        other = self.dataset.records.get(external_id="two")
        with self.assertRaisesMessage(services.WorkflowError, "not assigned"):
            self.vote(self.reviewer, record=other)
        with self.assertRaises(PermissionDenied):
            self.vote(self.viewer)
        with self.assertRaises(PermissionDenied):
            services.resolve_dispute(
                self.record, self.reviewer, label="positive", comment="No", version=1
            )

    def test_bad_labels_notes_and_versions(self):
        for label, comment, version in [
            ("other", "", 1),
            ("positive", "x" * 2001, 1),
            ("positive", "\x00", 1),
            ("positive", "\ud800", 1),
            ("positive", "", True),
            ("positive", "", 0),
        ]:
            with self.subTest(version=version), self.assertRaises(services.WorkflowError):
                services.submit_review(
                    self.record, self.reviewer, label=label, comment=comment, version=version
                )

    def test_assignments_fill_available_slots_once(self):
        count = services.assign_records(self.dataset, self.manager, self.reviewer.pk, 10)
        self.assertEqual(count, 1)
        self.assertEqual(
            services.assign_records(self.dataset, self.manager, self.reviewer.pk, 10), 0
        )
        self.assertEqual(services.assign_records(self.dataset, self.manager, self.second.pk, 10), 1)
        self.assertEqual(
            services.assign_records(self.dataset, self.manager, self.manager.pk, 10), 0
        )

    def test_viewer_cannot_receive_assignment(self):
        with self.assertRaisesMessage(services.WorkflowError, "active manager or reviewer"):
            services.assign_records(self.dataset, self.manager, self.viewer.pk, 1)
        with self.assertRaisesMessage(services.WorkflowError, "between"):
            services.assign_records(self.dataset, self.manager, self.reviewer.pk, 0)

    def test_last_manager_cannot_be_demoted(self):
        with self.assertRaisesMessage(services.WorkflowError, "at least one"):
            services.add_member(self.dataset, self.manager, "manager", "reviewer")
        services.add_member(self.dataset, self.manager, "second", "manager")
        services.add_member(self.dataset, self.manager, "manager", "reviewer")
        self.assertEqual(
            Membership.objects.get(dataset=self.dataset, user=self.manager).role, "reviewer"
        )

    def test_member_validation_and_pending_work(self):
        for username, role in [("missing", "reviewer"), ("viewer", "wrong")]:
            with self.assertRaises(services.WorkflowError):
                services.add_member(self.dataset, self.manager, username, role)
        with self.assertRaisesMessage(services.WorkflowError, "still has assignments"):
            services.add_member(self.dataset, self.manager, "reviewer", "viewer")

    def test_database_rejects_duplicate_votes(self):
        self.vote(self.reviewer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(record=self.record, reviewer=self.reviewer, label="negative")

    def test_audit_cannot_be_edited_or_deleted_through_model(self):
        event = AuditEvent.objects.first()
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()


class MetricTests(WorkspaceTestCase):
    def test_empty_metrics_have_no_invented_agreement(self):
        metrics = services.dataset_metrics(self.dataset)
        self.assertEqual(metrics["total"], 2)
        self.assertIsNone(metrics["agreement"])
        self.assertIsNone(metrics["fleiss_kappa"])

    def test_incomplete_votes_do_not_enter_agreement_denominator(self):
        self.vote(self.reviewer)
        self.assertIsNone(services.dataset_metrics(self.dataset)["agreement"])
        self.vote(self.second)
        metrics = services.dataset_metrics(self.dataset)
        self.assertEqual(
            (metrics["complete"], metrics["unanimous"], metrics["agreement"]), (1, 1, 100)
        )
        self.assertIsNone(metrics["fleiss_kappa"])

    def test_known_fleiss_kappa_and_adjudication_do_not_inflate_agreement(self):
        self.vote(self.reviewer)
        self.vote(self.second, "negative")
        services.resolve_dispute(
            self.record, self.manager, label="neutral", comment="Mixed", version=self.record.version
        )
        other = self.dataset.records.get(external_id="two")
        services.assign_records(self.dataset, self.manager, self.reviewer.pk, 1)
        services.assign_records(self.dataset, self.manager, self.second.pk, 1)
        self.vote(self.reviewer, "positive", other)
        self.vote(self.second, "positive", other)
        metrics = services.dataset_metrics(self.dataset)
        self.assertEqual(metrics["agreement"], 50)
        self.assertEqual(metrics["pairwise_agreement"], 50)
        self.assertAlmostEqual(metrics["fleiss_kappa"], -1 / 3, places=4)
        self.assertEqual(metrics["decisions"], 2)
