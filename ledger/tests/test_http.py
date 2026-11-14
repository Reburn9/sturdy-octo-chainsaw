import csv
import io
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse

from ledger import services

from .base import WorkspaceTestCase


class HTMLTests(WorkspaceTestCase):
    def setUp(self):
        self.client.force_login(self.manager)

    def test_workspace_pages_render_and_views_do_not_mutate_on_get(self):
        events = self.dataset.events.count()
        for name, args in [
            ("dashboard", []),
            ("dataset", [self.dataset.pk]),
            ("dataset-create", []),
            ("dataset-import", [self.dataset.pk]),
            ("members", [self.dataset.pk]),
            ("assignments", [self.dataset.pk]),
            ("audit", [self.dataset.pk]),
            ("queue", []),
            ("record", [self.record.pk]),
        ]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.assertEqual(events, self.dataset.events.count())

    def test_anonymous_users_redirect_to_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/"), "/accounts/login/?next=/")
        self.assertContains(self.client.get(reverse("login")), "Welcome back.")

    def test_create_dataset_validates_label_contract(self):
        data = {
            "name": "New",
            "description": "A real review workflow",
            "labels": "yes, no",
            "required_reviews": 2,
        }
        response = self.client.post(reverse("dataset-create"), data)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("dataset-create"), {**data, "labels": "yes,yes"})
        self.assertContains(response, "unique")
        for labels in ["yes,", "only-one", "x" * 61 + ",no"]:
            self.assertContains(
                self.client.post(reverse("dataset-create"), {**data, "labels": labels}), "errorlist"
            )

    def test_import_form_saves_valid_rows_and_shows_errors(self):
        url = reverse("dataset-import", args=[self.dataset.pk])
        good = SimpleUploadedFile("data.csv", b"id,text\nnew,Fresh imported text\n")
        self.assertEqual(self.client.post(url, {"file": good}).status_code, 302)
        bad = SimpleUploadedFile("bad.csv", b"id,text\nx,\n")
        self.assertContains(self.client.post(url, {"file": bad}), "Row 2")

    def test_members_and_assignments_forms_use_workflow_rules(self):
        url = reverse("members", args=[self.dataset.pk])
        self.assertContains(
            self.client.post(url, {"username": "nobody", "role": "viewer"}), "No active user"
        )
        self.assertEqual(
            self.client.post(url, {"username": "outsider", "role": "viewer"}).status_code, 302
        )
        assign = reverse("assignments", args=[self.dataset.pk])
        self.assertEqual(
            self.client.post(assign, {"reviewer": self.reviewer.pk, "count": 1}).status_code, 302
        )

    def test_unrelated_dataset_is_hidden_and_viewer_cannot_manage(self):
        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse("dataset", args=[self.dataset.pk])).status_code, 404
        )
        self.client.force_login(self.viewer)
        for name in ["members", "assignments", "dataset-import"]:
            self.assertEqual(
                self.client.get(reverse(name, args=[self.dataset.pk])).status_code, 403
            )

    def test_filters_find_pending_agreed_disputed_and_resolved_records(self):
        url = reverse("dataset", args=[self.dataset.pk])
        self.assertEqual(len(self.client.get(url + "?state=pending").context["page"]), 2)
        self.vote(self.reviewer)
        self.assertEqual(len(self.client.get(url + "?state=in_review").context["page"]), 1)
        self.vote(self.second)
        self.assertEqual(len(self.client.get(url + "?state=agreed&q=useful").context["page"]), 1)
        self.vote(self.second, "negative")
        self.assertEqual(len(self.client.get(url + "?state=disputed").context["page"]), 1)
        services.resolve_dispute(
            self.record, self.manager, label="neutral", comment="Mixed", version=self.record.version
        )
        self.assertEqual(len(self.client.get(url + "?state=resolved").context["page"]), 1)

    def test_reviewer_cannot_see_other_votes_before_submitting(self):
        self.vote(self.second, "negative")
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse("record", args=[self.record.pk]))
        self.assertFalse(response.context["show_votes"])
        self.assertNotContains(response, "Independent reviews</h2>")
        response = self.client.post(
            reverse("record", args=[self.record.pk]),
            {
                "label": "positive",
                "version": self.record.version,
                "comment": "Independent judgment",
                "action": "review",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.client.get(reverse("record", args=[self.record.pk])).context["show_votes"]
        )
        events = self.client.get(reverse("audit", args=[self.dataset.pk])).context["page"]
        self.assertTrue(all(event.actor_id == self.reviewer.pk for event in events))

    def test_queue_continues_after_success_and_stale_form_shows_conflict(self):
        self.client.force_login(self.reviewer)
        url = reverse("record", args=[self.record.pk])
        self.assertEqual(
            self.client.post(
                url + "?next=queue", {"label": "positive", "version": 1, "action": "review"}
            ).status_code,
            302,
        )
        response = self.client.post(url, {"label": "negative", "version": 1, "action": "review"})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Reload", status_code=409)

    def test_manager_can_adjudicate_from_html(self):
        self.vote(self.reviewer)
        self.vote(self.second, "negative")
        response = self.client.post(
            reverse("record", args=[self.record.pk]),
            {
                "label": "neutral",
                "comment": "Mixed evidence",
                "version": self.record.version,
                "action": "resolve",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.record.refresh_from_db()
        self.assertEqual(self.record.final_label, "neutral")

    def test_csrf_is_required_for_html_and_api_writes(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.reviewer)
        self.assertEqual(
            browser.post(
                reverse("api-review", args=[self.record.pk]),
                self.payload(),
                content_type="application/json",
            ).status_code,
            403,
        )
        browser.get(reverse("record", args=[self.record.pk]))
        token = browser.cookies["csrftoken"].value
        self.assertEqual(
            browser.post(
                reverse("api-review", args=[self.record.pk]),
                self.payload(),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
            ).status_code,
            200,
        )

    def test_record_content_is_escaped(self):
        self.record.text = '<script>alert("unsafe")</script>'
        self.record.save(update_fields=["text"])
        response = self.client.get(reverse("record", args=[self.record.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("unsafe")</script>')


class ExportTests(WorkspaceTestCase):
    def setUp(self):
        self.client.force_login(self.viewer)

    def test_exports_only_include_decided_records_and_are_audited(self):
        self.vote(self.reviewer)
        self.vote(self.second)
        url = reverse("export", args=[self.dataset.pk])
        response = self.client.get(url + "?format=csv")
        rows = list(csv.DictReader(io.StringIO(b"".join(response.streaming_content).decode())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "one")
        self.assertEqual(self.dataset.events.first().kind, "export.created")
        response = self.client.get(url + "?format=jsonl")
        self.assertEqual(json.loads(b"".join(response.streaming_content))["label"], "positive")
        self.assertEqual(self.client.get(url + "?format=xml").status_code, 400)

    def test_csv_formula_cells_are_escaped_but_jsonl_is_faithful(self):
        self.record.text = '=HYPERLINK("https://example.invalid")'
        self.record.save(update_fields=["text"])
        self.vote(self.reviewer)
        self.vote(self.second)
        url = reverse("export", args=[self.dataset.pk])
        response = self.client.get(url + "?format=csv")
        row = next(csv.DictReader(io.StringIO(b"".join(response.streaming_content).decode())))
        self.assertTrue(row["text"].startswith("'="))
        response = self.client.get(url + "?format=jsonl")
        self.assertTrue(json.loads(b"".join(response.streaming_content))["text"].startswith("="))

    def test_reviewers_cannot_export_other_labels(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(
            self.client.get(reverse("export", args=[self.dataset.pk])).status_code, 403
        )


class APITests(WorkspaceTestCase):
    def setUp(self):
        self.client.force_login(self.reviewer)
        self.url = reverse("api-review", args=[self.record.pk])

    def test_api_auth_and_dataset_isolation(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("api-datasets")).status_code, 401)
        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse("api-dataset", args=[self.dataset.pk])).status_code, 404
        )
        self.assertEqual(self.client.get(reverse("api-datasets")).json()["count"], 0)

    def test_lists_are_paginated_and_versioned(self):
        self.assertEqual(self.client.get(reverse("api-datasets")).json()["count"], 1)
        url = reverse("api-records", args=[self.dataset.pk])
        data = self.client.get(url).json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["results"][0]["version"], 1)
        self.assertEqual(self.client.get(url + "?page=0").status_code, 400)
        self.assertEqual(self.client.get(url + "?page=invalid").status_code, 400)
        self.assertEqual(self.client.get(url + "?page=2").status_code, 404)
        metrics = self.client.get(reverse("api-dataset", args=[self.dataset.pk])).json()["metrics"]
        self.assertIsNone(metrics["agreement"])

    def test_review_success_edit_and_conflict(self):
        response = self.client.post(self.url, self.payload(), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(
            self.client.post(self.url, self.payload(), content_type="application/json").status_code,
            409,
        )
        response = self.client.post(
            self.url, self.payload(version=2, label="negative"), content_type="application/json"
        )
        self.assertEqual(response.json()["reviews"][0]["label"], "negative")

    def test_blind_votes_and_viewer_write_protection(self):
        self.vote(self.second, "negative")
        data = self.client.get(reverse("api-records", args=[self.dataset.pk])).json()
        self.assertEqual(data["results"][0]["reviews"], [])
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.post(self.url, self.payload(), content_type="application/json").status_code,
            403,
        )

    def test_api_adjudication(self):
        self.vote(self.reviewer)
        self.vote(self.second, "negative")
        self.client.force_login(self.manager)
        url = reverse("api-resolve", args=[self.record.pk])
        response = self.client.post(
            url, self.payload(label="neutral"), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "resolved")

    def test_malformed_requests_and_method_contract(self):
        for body in [
            "{bad",
            "[]",
            "{}",
            '{"label":"positive","version":1,"extra":true}',
            "[" * 1500 + "]" * 1500,
        ]:
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.post(self.url, body, content_type="application/json").status_code,
                    400,
                )
        self.assertEqual(
            self.client.post(self.url, "x" * 10001, content_type="application/json").status_code,
            413,
        )
        self.assertEqual(
            self.client.post(self.url, "text", content_type="text/plain").status_code, 415
        )
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(
            self.client.post(
                self.url, self.payload(version=True), content_type="application/json"
            ).status_code,
            400,
        )

    def test_health_reports_database_failure_without_details(self):
        self.assertEqual(self.client.get(reverse("health")).json(), {"status": "ok"})
        with patch(
            "ledger.views.connection.cursor", side_effect=DatabaseError("private connection string")
        ):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
