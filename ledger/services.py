"""Workflow rules live here so the HTML views, API, and CLI use the same invariants."""

import csv
import hashlib
import io
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from .access import require_role
from .models import Assignment, AuditEvent, Dataset, ImportBatch, Membership, Record, Review

MAX_UPLOAD = 5 * 1024 * 1024
MAX_ROWS = 10000


class WorkflowError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ImportResult:
    created: int
    duplicate_ids: int
    duplicate_text: int


def audit(dataset, actor, kind, record=None, **details):
    AuditEvent.objects.create(
        dataset=dataset, actor=actor, kind=kind, record=record, details=details
    )


@transaction.atomic
def create_dataset(actor, *, name, description, labels, required_reviews=2):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise WorkflowError("Dataset names must contain 1–120 characters.")
    if (
        not isinstance(labels, list)
        or not 2 <= len(labels) <= 12
        or any(
            not isinstance(label, str) or not label.strip() or len(label) > 60 for label in labels
        )
        or len(set(labels)) != len(labels)
    ):
        raise WorkflowError("Provide 2–12 unique labels of 1–60 characters.")
    if (
        isinstance(required_reviews, bool)
        or not isinstance(required_reviews, int)
        or not 2 <= required_reviews <= 5
    ):
        raise WorkflowError("Require 2–5 independent reviews.")
    dataset = Dataset.objects.create(
        name=name.strip(),
        description=description,
        labels=labels,
        required_reviews=required_reviews,
        created_by=actor,
    )
    Membership.objects.create(dataset=dataset, user=actor, role=Membership.Role.MANAGER)
    audit(dataset, actor, "dataset.created", labels=labels, required_reviews=required_reviews)
    return dataset


def fingerprint(text):
    normalized = " ".join(unicodedata.normalize("NFKC", text).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_upload(data, filename):
    if len(data) > MAX_UPLOAD:
        raise WorkflowError("Uploads are limited to 5 MiB.")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkflowError("Use a UTF-8 encoded CSV or JSONL file.") from exc
    if filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(content), strict=True)
        try:
            headers = reader.fieldnames or []
        except csv.Error as exc:
            raise WorkflowError(f"Invalid CSV: {exc}") from exc
        if len(headers) != len(set(headers)) or not {"id", "text"}.issubset(headers):
            raise WorkflowError("CSV requires unique column headers including id and text.")
        if set(headers) - {"id", "text", "metadata"}:
            raise WorkflowError("Supported CSV columns: id, text, and optional metadata.")
        source = enumerate(reader, start=2)
    elif filename.lower().endswith(".jsonl"):
        source = (
            (number, line) for number, line in enumerate(content.splitlines(), 1) if line.strip()
        )
    else:
        raise WorkflowError("Upload a .csv or .jsonl file.")
    rows = []
    try:
        for number, raw in source:
            if len(rows) >= MAX_ROWS:
                raise WorkflowError("Each import is limited to 10,000 records.")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (json.JSONDecodeError, RecursionError) as exc:
                    raise WorkflowError(f"Row {number}: invalid JSON.") from exc
            if not isinstance(raw, dict) or set(raw) - {"id", "text", "metadata"}:
                raise WorkflowError(f"Row {number}: use only id, text, and metadata fields.")
            external_id, text = raw.get("id"), raw.get("text")
            if not isinstance(external_id, str) or not 1 <= len(external_id.strip()) <= 120:
                raise WorkflowError(
                    f"Row {number}: id must be a nonempty string of at most 120 characters."
                )
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 20000 or "\x00" in text:
                raise WorkflowError(
                    f"Row {number}: text must contain 1–20,000 characters and no NUL bytes."
                )
            if "\x00" in external_id:
                raise WorkflowError(f"Row {number}: id cannot contain NUL bytes.")
            try:
                (external_id + text).encode("utf-8")
            except UnicodeEncodeError as exc:
                raise WorkflowError(
                    f"Row {number}: id and text must contain valid Unicode."
                ) from exc
            metadata = raw.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata) if metadata.strip() else {}
                except (json.JSONDecodeError, RecursionError) as exc:
                    raise WorkflowError(f"Row {number}: metadata must be a JSON object.") from exc
            if not isinstance(metadata, dict):
                raise WorkflowError(f"Row {number}: metadata must be a JSON object.")
            try:
                encoded_metadata = json.dumps(metadata, allow_nan=False, ensure_ascii=False)
                metadata_bytes = encoded_metadata.encode("utf-8")
            except (ValueError, TypeError, RecursionError) as exc:
                raise WorkflowError(
                    f"Row {number}: metadata must contain valid finite JSON values."
                ) from exc
            values = [metadata]
            has_nul = False
            while values:
                value = values.pop()
                if isinstance(value, dict):
                    values.extend(value.keys())
                    values.extend(value.values())
                elif isinstance(value, list):
                    values.extend(value)
                elif isinstance(value, str) and "\x00" in value:
                    has_nul = True
                    break
            if len(metadata_bytes) > 20000 or has_nul:
                raise WorkflowError(
                    f"Row {number}: metadata is limited to 20,000 UTF-8 bytes and no NUL values."
                )
            rows.append((number, external_id.strip(), text.strip(), metadata))
    except csv.Error as exc:
        raise WorkflowError(f"Invalid CSV: {exc}") from exc
    if not rows:
        raise WorkflowError("The file contains no records.")
    return rows


@transaction.atomic
def import_records(dataset, actor, data, filename):
    require_role(actor, dataset, Membership.Role.MANAGER)
    rows = parse_upload(data, filename)
    # Taking a write lock also serializes SQLite imports; PostgreSQL holds a row lock.
    Dataset.objects.filter(pk=dataset.pk).update(updated_at=timezone.now())
    known_ids = dict(dataset.records.values_list("external_id", "fingerprint"))
    known_text = set(known_ids.values())
    pending, duplicate_ids, duplicate_text = [], 0, 0
    for number, external_id, text, metadata in rows:
        content_hash = fingerprint(text)
        if external_id in known_ids:
            if known_ids[external_id] != content_hash:
                raise WorkflowError(
                    f"Row {number}: id '{external_id}' already refers to different text."
                )
            duplicate_ids += 1
            continue
        known_ids[external_id] = content_hash
        if content_hash in known_text:
            duplicate_text += 1
            continue
        known_text.add(content_hash)
        pending.append(
            Record(
                dataset=dataset,
                external_id=external_id,
                text=text,
                metadata=metadata,
                fingerprint=content_hash,
            )
        )
    Record.objects.bulk_create(pending, batch_size=200)
    ImportBatch.objects.create(
        dataset=dataset,
        actor=actor,
        filename=filename[:200],
        created=len(pending),
        skipped=duplicate_ids + duplicate_text,
    )
    audit(
        dataset,
        actor,
        "import.completed",
        created=len(pending),
        duplicate_ids=duplicate_ids,
        duplicate_text=duplicate_text,
    )
    return ImportResult(len(pending), duplicate_ids, duplicate_text)


@transaction.atomic
def add_member(dataset, actor, username, role):
    require_role(actor, dataset, Membership.Role.MANAGER)
    if role not in Membership.Role.values:
        raise WorkflowError("Choose a valid dataset role.")
    user = get_user_model().objects.filter(username=username, is_active=True).first()
    if not user:
        raise WorkflowError(
            "No active user has that username. Create the account in the terminal first."
        )
    Dataset.objects.filter(pk=dataset.pk).update(updated_at=timezone.now())
    member = Membership.objects.filter(dataset=dataset, user=user).first()
    if member and member.role == Membership.Role.MANAGER and role != Membership.Role.MANAGER:
        if dataset.memberships.filter(role=Membership.Role.MANAGER).count() <= 1:
            raise WorkflowError("Keep at least one dataset manager.")
    if member and member.role != role and role == Membership.Role.VIEWER:
        unfinished = (
            Assignment.objects.filter(record__dataset=dataset, reviewer=user)
            .exclude(record__reviews__reviewer=user)
            .exists()
        )
        if unfinished:
            raise WorkflowError(
                "This reviewer still has assignments. Complete them before changing to Viewer."
            )
    Membership.objects.update_or_create(dataset=dataset, user=user, defaults={"role": role})
    audit(dataset, actor, "member.updated", username=user.username, role=role)


@transaction.atomic
def assign_records(dataset, actor, reviewer_id, count):
    require_role(actor, dataset, Membership.Role.MANAGER)
    if not 1 <= count <= 100:
        raise WorkflowError("Assign between 1 and 100 records at a time.")
    member = dataset.memberships.filter(
        user_id=reviewer_id,
        user__is_active=True,
        role__in=[Membership.Role.MANAGER, Membership.Role.REVIEWER],
    ).first()
    if not member:
        raise WorkflowError("Choose an active manager or reviewer in this dataset.")
    Dataset.objects.filter(pk=dataset.pk).update(updated_at=timezone.now())
    candidates = (
        dataset.records.filter(final_label="")
        .annotate(
            allocated=Count("assignments", distinct=True), votes=Count("reviews", distinct=True)
        )
        .filter(allocated__lt=dataset.required_reviews, votes__lt=dataset.required_reviews)
        .exclude(assignments__reviewer_id=reviewer_id)
        .order_by("votes", "created_at", "external_id")[:count]
    )
    records = list(candidates)
    Assignment.objects.bulk_create(
        [
            Assignment(record=record, reviewer_id=reviewer_id, assigned_by=actor)
            for record in records
        ]
    )
    if records:
        audit(
            dataset, actor, "assignment.created", reviewer=member.user.username, count=len(records)
        )
    return len(records)


def lock_version(record, expected):
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
        raise WorkflowError("A positive integer record version is required.")
    updated = Record.objects.filter(pk=record.pk, version=expected, final_label="").update(
        version=F("version") + 1
    )
    if not updated:
        raise WorkflowError("This record changed. Reload it before submitting again.", status=409)
    record.refresh_from_db()


def validate_label(dataset, label, comment):
    if label not in dataset.labels or not isinstance(label, str):
        raise WorkflowError("Choose a label from this dataset's label set.")
    if not isinstance(comment, str) or len(comment) > 2000 or "\x00" in comment:
        raise WorkflowError("Notes must be text of at most 2,000 characters.")
    try:
        comment.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkflowError("Notes must contain valid Unicode.") from exc


@transaction.atomic
def submit_review(record, actor, *, label, comment, version):
    require_role(actor, record.dataset, Membership.Role.MANAGER, Membership.Role.REVIEWER)
    validate_label(record.dataset, label, comment)
    if not record.assignments.filter(reviewer=actor).exists():
        raise WorkflowError("This record is not assigned to you.", status=403)
    lock_version(record, version)
    if not record.reviews.filter(reviewer=actor).exists():
        if record.reviews.count() >= record.dataset.required_reviews:
            raise WorkflowError(
                "This record has reached its independent review target.", status=409
            )
    review, _ = Review.objects.update_or_create(
        record=record, reviewer=actor, defaults={"label": label, "comment": comment.strip()}
    )
    audit(
        record.dataset,
        actor,
        "review.submitted",
        record=record,
        label=label,
        version=record.version,
    )
    return review


@transaction.atomic
def resolve_dispute(record, actor, *, label, comment, version):
    require_role(actor, record.dataset, Membership.Role.MANAGER)
    validate_label(record.dataset, label, comment)
    if not comment.strip():
        raise WorkflowError("Explain the adjudication decision in a short note.")
    lock_version(record, version)
    if record.state != "disputed":
        raise WorkflowError("Only disagreements with a complete set of reviews can be resolved.")
    record.final_label, record.resolved_by, record.resolution_note = label, actor, comment.strip()
    record.save(update_fields=["final_label", "resolved_by", "resolution_note"])
    audit(
        record.dataset,
        actor,
        "dispute.resolved",
        record=record,
        label=label,
        version=record.version,
    )


def dataset_metrics(dataset):
    states, distribution, reviewer_counts = Counter(), Counter(), Counter()
    matrix = []
    records = dataset.records.select_related("dataset").prefetch_related("reviews")
    for record in records.iterator(chunk_size=200):
        votes = list(record.reviews.all())
        states[record.state] += 1
        for review in votes:
            distribution[review.label] += 1
            reviewer_counts[review.reviewer_id] += 1
        if len(votes) == dataset.required_reviews:
            matrix.append(Counter(review.label for review in votes))
    complete = len(matrix)
    unanimous = sum(len(row) == 1 for row in matrix)
    pairwise, kappa = None, None
    if complete:
        n = dataset.required_reviews
        pairwise = (
            sum(
                sum(count * (count - 1) for count in row.values()) / (n * (n - 1)) for row in matrix
            )
            / complete
        )
        marginal = sum(matrix, Counter())
        expected = sum((count / (complete * n)) ** 2 for count in marginal.values())
        if expected < 1 - 1e-12:
            kappa = (pairwise - expected) / (1 - expected)
    total = sum(states.values())
    return {
        "total": total,
        "states": {
            state: states[state]
            for state in ["pending", "in_review", "agreed", "disputed", "resolved"]
        },
        "complete": complete,
        "unanimous": unanimous,
        "agreement": round(100 * unanimous / complete, 1) if complete else None,
        "pairwise_agreement": round(pairwise * 100, 1) if pairwise is not None else None,
        "fleiss_kappa": round(kappa, 4) if kappa is not None else None,
        "progress": round(100 * complete / total) if total else 0,
        "decisions": states["agreed"] + states["resolved"],
        "reviews": sum(distribution.values()),
        "distribution": {label: distribution[label] for label in dataset.labels},
        "reviewers": dict(reviewer_counts),
    }
