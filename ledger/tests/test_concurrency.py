from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from ledger import services
from ledger.models import Assignment, Membership


@skipUnless(
    connection.vendor == "postgresql", "Real competing writers are verified on PostgreSQL in CI."
)
class ConcurrentVoteTests(TransactionTestCase):
    def test_only_one_writer_can_advance_a_record_version(self):
        User = get_user_model()
        manager = User.objects.create_user("race-manager")
        reviewers = [User.objects.create_user(f"race-{i}") for i in range(2)]
        dataset = services.create_dataset(
            manager, name="Race", description="Version conflict test", labels=["yes", "no"]
        )
        services.import_records(dataset, manager, b"id,text\nx,A concurrent review\n", "test.csv")
        record = dataset.records.get()
        for user in reviewers:
            Membership.objects.create(dataset=dataset, user=user, role="reviewer")
            Assignment.objects.create(record=record, reviewer=user, assigned_by=manager)
        barrier = Barrier(2)

        def writer(user_id):
            close_old_connections()
            try:
                user = User.objects.get(pk=user_id)
                local_record = type(record).objects.select_related("dataset").get(pk=record.pk)
                barrier.wait(timeout=10)
                try:
                    services.submit_review(
                        local_record, user, label="yes", comment="Concurrent", version=1
                    )
                    return 200
                except services.WorkflowError as exc:
                    return exc.status
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, [user.pk for user in reviewers]))
        self.assertCountEqual(results, [200, 409])
        record.refresh_from_db()
        self.assertEqual(record.version, 2)
        self.assertEqual(record.reviews.count(), 1)
        self.assertEqual(dataset.events.filter(kind="review.submitted").count(), 1)
