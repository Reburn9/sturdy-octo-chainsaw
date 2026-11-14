from django.db.models import Count, F, Q

from .access import visible_datasets
from .models import Record


def annotated_records(dataset):
    return (
        dataset.records.select_related("dataset")
        .prefetch_related("reviews")
        .annotate(
            vote_count=Count("reviews", distinct=True),
            distinct_labels=Count("reviews__label", distinct=True),
        )
        .order_by("created_at", "external_id")
    )


def filter_state(records, state):
    if state == "resolved":
        return records.exclude(final_label="")
    if state == "pending":
        return records.filter(final_label="", vote_count=0)
    if state == "in_review":
        return records.filter(
            final_label="", vote_count__gt=0, vote_count__lt=F("dataset__required_reviews")
        )
    if state in {"agreed", "disputed"}:
        records = records.filter(final_label="", vote_count__gte=F("dataset__required_reviews"))
        return (
            records.filter(distinct_labels=1)
            if state == "agreed"
            else records.filter(distinct_labels__gt=1)
        )
    return records


def queue_for(user):
    return (
        Record.objects.filter(
            dataset__in=visible_datasets(user), assignments__reviewer=user, final_label=""
        )
        .exclude(reviews__reviewer=user)
        .select_related("dataset")
        .prefetch_related("reviews")
        .annotate(vote_count=Count("reviews", distinct=True))
        .filter(vote_count__lt=F("dataset__required_reviews"))
        .order_by("created_at", "external_id")
    )


def search_records(records, text):
    return (
        records.filter(Q(text__icontains=text) | Q(external_id__icontains=text))
        if text
        else records
    )
