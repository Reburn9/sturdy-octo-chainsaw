import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Dataset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, max_length=2000)
    labels = models.JSONField(default=list)
    required_reviews = models.PositiveSmallIntegerField(
        default=2, validators=[MinValueValidator(2), MaxValueValidator(5)]
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(required_reviews__gte=2, required_reviews__lte=5),
                name="valid_review_target",
            )
        ]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        MANAGER = "manager", "Manager"
        REVIEWER = "reviewer", "Reviewer"
        VIEWER = "viewer", "Viewer"

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    role = models.CharField(max_length=12, choices=Role.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["dataset", "user"], name="unique_member")]


class Record(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="records")
    external_id = models.CharField(max_length=120)
    text = models.TextField(max_length=20000)
    metadata = models.JSONField(default=dict)
    fingerprint = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    final_label = models.CharField(max_length=60, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resolutions",
    )
    resolution_note = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "external_id"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "external_id"], name="unique_external_id"),
            models.UniqueConstraint(fields=["dataset", "fingerprint"], name="unique_content"),
        ]
        indexes = [models.Index(fields=["dataset", "created_at"])]

    @property
    def state(self):
        if self.final_label:
            return "resolved"
        votes = [review.label for review in self.reviews.all()]
        if len(votes) < self.dataset.required_reviews:
            return "in_review" if votes else "pending"
        return "agreed" if len(set(votes)) == 1 else "disputed"

    @property
    def decision(self):
        if self.final_label:
            return self.final_label
        votes = [review.label for review in self.reviews.all()]
        if len(votes) >= self.dataset.required_reviews and len(set(votes)) == 1:
            return votes[0]
        return None


class Assignment(models.Model):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="assignments")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments_made"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["record", "reviewer"], name="unique_assignment")
        ]


class Review(models.Model):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    label = models.CharField(max_length=60)
    comment = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["record", "reviewer"], name="unique_review")]


class ImportBatch(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="imports")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    filename = models.CharField(max_length=200)
    created = models.PositiveIntegerField()
    skipped = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AuditEvent(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=40)
    record = models.ForeignKey(Record, null=True, on_delete=models.SET_NULL)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Audit events cannot be edited through the application.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events cannot be deleted through the application.")

    @property
    def description(self):
        return {
            "dataset.created": "Created the dataset",
            "import.completed": "Imported records",
            "assignment.created": "Assigned review work",
            "member.updated": "Updated dataset access",
            "review.submitted": "Submitted a review",
            "dispute.resolved": "Resolved a disagreement",
            "export.created": "Exported dataset decisions",
        }.get(self.kind, self.kind)
