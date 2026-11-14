import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied

from ledger import services

from .base import WorkspaceTestCase


class ImportTests(WorkspaceTestCase):
    def test_retry_skips_ids_and_normalized_duplicate_content(self):
        result = services.import_records(
            self.dataset,
            self.manager,
            b"id,text\none,A useful new feature\nnew,  A   useful new feature \nthree,Something else\n",
            "data.csv",
        )
        self.assertEqual((result.created, result.duplicate_ids, result.duplicate_text), (1, 1, 1))
        self.assertEqual(self.dataset.records.count(), 3)

    def test_conflicting_id_rolls_back_valid_rows_and_audit(self):
        events = self.dataset.events.count()
        with self.assertRaisesMessage(services.WorkflowError, "different text"):
            services.import_records(
                self.dataset,
                self.manager,
                b"id,text\nnew,New content\none,Changed content\n",
                "data.csv",
            )
        self.assertEqual(self.dataset.records.count(), 2)
        self.assertEqual(self.dataset.events.count(), events)

    def test_invalid_final_row_prevents_partial_import(self):
        with self.assertRaisesMessage(services.WorkflowError, "Row 3"):
            services.import_records(
                self.dataset, self.manager, b"id,text\nnew,Valid\nbad,\n", "data.csv"
            )
        self.assertFalse(self.dataset.records.filter(external_id="new").exists())

    def test_jsonl_utf8_bom_and_metadata(self):
        data = "\ufeff" + json.dumps(
            {"id": "café", "text": "Très bien", "metadata": {"language": "fr"}}
        )
        result = services.import_records(self.dataset, self.manager, data.encode(), "data.jsonl")
        self.assertEqual(result.created, 1)
        self.assertEqual(self.dataset.records.get(external_id="café").metadata, {"language": "fr"})

    def test_duplicate_id_within_upload_cannot_change_content(self):
        with self.assertRaisesMessage(services.WorkflowError, "different text"):
            services.import_records(
                self.dataset, self.manager, b"id,text\nx,One\nx,Two\n", "data.csv"
            )

    def test_invalid_input_shapes(self):
        cases = [
            (b"\xff", "data.csv", "UTF-8"),
            (b"id,text\n", "data.txt", ".csv or .jsonl"),
            (b"wrong,text\na,b\n", "data.csv", "headers"),
            (b"id,text,text\na,b,c\n", "data.csv", "headers"),
            (b"id,text,extra\na,b,c\n", "data.csv", "Supported CSV"),
            (b"id,text\n", "data.csv", "no records"),
            (b"{bad}\n", "data.jsonl", "invalid JSON"),
            (b"[]\n", "data.jsonl", "fields"),
            (b'{"id":3,"text":"ok"}', "data.jsonl", "id must"),
            (b'{"id":"x","text":"ok","metadata":[]}', "data.jsonl", "JSON object"),
            (b"id,text,metadata\nx,ok,not-json\n", "data.csv", "JSON object"),
            (b"id,text\nx,ok,extra\n", "data.csv", "fields"),
            (b'id,text\nx,"unfinished', "data.csv", "Invalid CSV"),
            (b'{"id":"x","text":"a\\u0000b"}', "data.jsonl", "NUL"),
        ]
        for data, filename, error in cases:
            with self.subTest(filename=filename, error=error):
                with self.assertRaisesMessage(services.WorkflowError, error):
                    services.parse_upload(data, filename)

    def test_size_and_row_limits(self):
        with (
            patch.object(services, "MAX_UPLOAD", 3),
            self.assertRaisesMessage(services.WorkflowError, "5 MiB"),
        ):
            services.parse_upload(b"long", "data.csv")
        with (
            patch.object(services, "MAX_ROWS", 1),
            self.assertRaisesMessage(services.WorkflowError, "10,000"),
        ):
            services.parse_upload(b"id,text\na,One\nb,Two\n", "data.csv")

    def test_non_manager_cannot_import(self):
        with self.assertRaises(PermissionDenied):
            services.import_records(self.dataset, self.reviewer, b"id,text\nx,ok\n", "data.csv")

    def test_invalid_unicode_and_nonfinite_metadata_fail_as_validation_errors(self):
        for data in [
            b'{"id":"x","text":"\\ud800"}',
            b'{"id":"x","text":"ok","metadata":{"score":NaN}}',
            b'{"id":"x","text":"ok","metadata":{"context":"a\\u0000b"}}',
            b'{"id":"x","text":"ok","metadata":{"context":"\\ud800"}}',
        ]:
            with self.subTest(data=data), self.assertRaises(services.WorkflowError):
                services.parse_upload(data, "data.jsonl")
        data = json.dumps({"id": "x", "text": "ok", "metadata": {"escaped": "\\u0000"}}).encode()
        self.assertEqual(services.parse_upload(data, "data.jsonl")[0][3], {"escaped": "\\u0000"})
