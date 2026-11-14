import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, connection
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .access import get_dataset, require_role, role_for, visible_datasets
from .exports import export_csv, export_jsonl
from .forms import AssignmentForm, DatasetForm, ImportForm, MemberForm, ReviewForm
from .models import AuditEvent, Membership, Record
from .selectors import annotated_records, filter_state, queue_for, search_records


def dataset_context(user, dataset):
    return {"dataset": dataset, "role": role_for(user, dataset), "active": "datasets"}


@login_required
@require_GET
def dashboard(request):
    datasets = list(visible_datasets(request.user)[:20])
    total, complete, decisions, disputed, unanimous = 0, 0, 0, 0, 0
    for dataset in datasets:
        dataset.metrics = services.dataset_metrics(dataset)
        total += dataset.metrics["total"]
        complete += dataset.metrics["complete"]
        unanimous += dataset.metrics["unanimous"]
        decisions += dataset.metrics["decisions"]
        disputed += dataset.metrics["states"]["disputed"]
    events = AuditEvent.objects.filter(dataset__in=datasets).select_related("dataset", "actor")[:6]
    return render(
        request,
        "ledger/dashboard.html",
        {
            "datasets": datasets,
            "total": total,
            "complete": complete,
            "decisions": decisions,
            "disputed": disputed,
            "agreement": round(100 * unanimous / complete, 1) if complete else None,
            "queue_count": queue_for(request.user).count(),
            "events": events,
            "active": "overview",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def dataset_create(request):
    form = DatasetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        dataset = services.create_dataset(request.user, **form.cleaned_data)
        messages.success(request, "Dataset created. Import records to begin.")
        return redirect("dataset", dataset_id=dataset.pk)
    return render(
        request,
        "ledger/form_page.html",
        {
            "form": form,
            "title": "Create a dataset",
            "eyebrow": "A new review workspace",
            "description": "Define your label set and review target. Both stay fixed so agreement remains comparable.",
            "button": "Create dataset",
            "active": "datasets",
        },
    )


@login_required
@require_GET
def dataset_detail(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    query = request.GET.get("q", "").strip()[:200]
    state = request.GET.get("state", "")
    records = search_records(filter_state(annotated_records(dataset), state), query)
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "ledger/dataset.html",
        {
            **dataset_context(request.user, dataset),
            "metrics": services.dataset_metrics(dataset),
            "page": page,
            "query": query,
            "state": state,
            "states": ["pending", "in_review", "agreed", "disputed", "resolved"],
            "imports": dataset.imports.select_related("actor")[:3],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def dataset_import(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    require_role(request.user, dataset, Membership.Role.MANAGER)
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            result = services.import_records(
                dataset, request.user, upload.read(services.MAX_UPLOAD + 1), upload.name
            )
        except services.WorkflowError as exc:
            form.add_error("file", str(exc))
        else:
            messages.success(
                request,
                f"Imported {result.created} records. Skipped {result.duplicate_ids} duplicate IDs and {result.duplicate_text} duplicate texts.",
            )
            return redirect("dataset", dataset_id=dataset.pk)
    return render(
        request, "ledger/import.html", {**dataset_context(request.user, dataset), "form": form}
    )


@login_required
@require_http_methods(["GET", "POST"])
def members(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    require_role(request.user, dataset, Membership.Role.MANAGER)
    form = MemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.add_member(dataset, request.user, **form.cleaned_data)
        except services.WorkflowError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Dataset access updated.")
            return redirect("members", dataset_id=dataset.pk)
    return render(
        request,
        "ledger/members.html",
        {
            **dataset_context(request.user, dataset),
            "form": form,
            "members": dataset.memberships.select_related("user").order_by(
                "role", "user__username"
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def assignments(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    require_role(request.user, dataset, Membership.Role.MANAGER)
    form = AssignmentForm(request.POST or None, dataset=dataset)
    if request.method == "POST" and form.is_valid():
        try:
            count = services.assign_records(
                dataset, request.user, form.cleaned_data["reviewer"].pk, form.cleaned_data["count"]
            )
        except services.WorkflowError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                f"Assigned {count} records. Each record has at most {dataset.required_reviews} review slots.",
            )
            return redirect("dataset", dataset_id=dataset.pk)
    return render(
        request,
        "ledger/form_page.html",
        {
            **dataset_context(request.user, dataset),
            "form": form,
            "title": "Assign independent reviews",
            "eyebrow": dataset.name,
            "button": "Assign records",
            "description": "Records with the fewest votes are assigned first. Existing assignments and completed records are skipped.",
        },
    )


@login_required
@require_GET
def review_queue(request):
    records = queue_for(request.user)
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    return render(request, "ledger/queue.html", {"page": page, "active": "queue"})


def visible_record(user, record_id):
    return get_object_or_404(
        Record.objects.select_related("dataset", "resolved_by").prefetch_related(
            "reviews__reviewer"
        ),
        pk=record_id,
        dataset__in=visible_datasets(user),
    )


@login_required
@require_http_methods(["GET", "POST"])
def record_detail(request, record_id):
    record = visible_record(request.user, record_id)
    role = role_for(request.user, record.dataset)
    own_review = next(
        (vote for vote in record.reviews.all() if vote.reviewer_id == request.user.pk), None
    )
    is_resolve = request.POST.get("action") == "resolve"
    form = ReviewForm(
        request.POST or None,
        dataset=record.dataset,
        initial={
            "version": record.version,
            "label": own_review.label if own_review else None,
            "comment": own_review.comment if own_review else "",
        },
    )
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            action = services.resolve_dispute if is_resolve else services.submit_review
            action(record, request.user, **form.cleaned_data)
        except services.WorkflowError as exc:
            form.add_error(None, str(exc))
            status = exc.status
        else:
            messages.success(request, "Adjudication saved." if is_resolve else "Review saved.")
            if request.GET.get("next") == "queue":
                next_record = queue_for(request.user).first()
                if next_record:
                    return redirect(reverse("record", args=[next_record.pk]) + "?next=queue")
                return redirect("queue")
            return redirect("record", record_id=record.pk)
    can_review = (
        role in {Membership.Role.MANAGER, Membership.Role.REVIEWER}
        and record.assignments.filter(reviewer=request.user).exists()
        and not record.final_label
    )
    return render(
        request,
        "ledger/record.html",
        {
            **dataset_context(request.user, record.dataset),
            "record": record,
            "form": form,
            "can_review": can_review,
            "can_resolve": role == Membership.Role.MANAGER and record.state == "disputed",
            "show_votes": role != Membership.Role.REVIEWER or own_review is not None,
            "own_review": own_review,
        },
        status=status,
    )


@login_required
@require_GET
def audit_log(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    events = dataset.events.select_related("actor", "record")
    if role_for(request.user, dataset) == Membership.Role.REVIEWER:
        events = events.filter(actor=request.user)
    return render(
        request,
        "ledger/audit.html",
        {
            **dataset_context(request.user, dataset),
            "page": Paginator(events, 30).get_page(request.GET.get("page")),
        },
    )


@login_required
@require_GET
def dataset_export(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    kind = request.GET.get("format", "csv")
    if kind not in {"csv", "jsonl"}:
        return HttpResponse("Choose csv or jsonl.", status=400, content_type="text/plain")
    require_role(request.user, dataset, Membership.Role.MANAGER, Membership.Role.VIEWER)
    services.audit(dataset, request.user, "export.created", format=kind)
    response = StreamingHttpResponse(
        export_csv(dataset) if kind == "csv" else export_jsonl(dataset),
        content_type="text/csv; charset=utf-8" if kind == "csv" else "application/x-ndjson",
    )
    response["Content-Disposition"] = f'attachment; filename="labelledger-{dataset.pk}.{kind}"'
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM ledger_dataset LIMIT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def api_view(methods):
    def decorator(function):
        @wraps(function)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"error": "Authentication required."}, status=401)
            if request.method not in methods:
                response = JsonResponse({"error": "Method not allowed."}, status=405)
                response["Allow"] = ", ".join(methods)
                return response
            try:
                return function(request, *args, **kwargs)
            except Http404:
                return JsonResponse({"error": "Not found."}, status=404)
            except PermissionDenied:
                return JsonResponse({"error": "Forbidden."}, status=403)
            except services.WorkflowError as exc:
                return JsonResponse({"error": str(exc)}, status=exc.status)

        return wrapped

    return decorator


def api_page(request, records):
    try:
        number = int(request.GET.get("page", "1"))
        if number < 1:
            raise ValueError
    except ValueError as exc:
        raise services.WorkflowError("page must be a positive integer.") from exc
    paginator = Paginator(records, 50)
    if number > paginator.num_pages:
        raise Http404
    return paginator.page(number)


def record_json(record, user):
    own_vote = any(review.reviewer_id == user.pk for review in record.reviews.all())
    show_votes = role_for(user, record.dataset) != Membership.Role.REVIEWER or own_vote
    return {
        "id": str(record.pk),
        "external_id": record.external_id,
        "text": record.text,
        "metadata": record.metadata,
        "version": record.version,
        "state": record.state
        if show_votes
        else ("in_review" if record.reviews.all() else "pending"),
        "decision": record.decision if show_votes else None,
        "reviews": [
            {"reviewer_id": review.reviewer_id, "label": review.label, "comment": review.comment}
            for review in record.reviews.all()
        ]
        if show_votes
        else [],
    }


@api_view(["GET"])
def api_datasets(request):
    page = api_page(request, visible_datasets(request.user))
    return JsonResponse(
        {
            "count": page.paginator.count,
            "page": page.number,
            "results": [
                {
                    "id": str(d.pk),
                    "name": d.name,
                    "labels": d.labels,
                    "required_reviews": d.required_reviews,
                }
                for d in page
            ],
        }
    )


@api_view(["GET"])
def api_dataset(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    return JsonResponse(
        {
            "id": str(dataset.pk),
            "name": dataset.name,
            "labels": dataset.labels,
            "required_reviews": dataset.required_reviews,
            "metrics": services.dataset_metrics(dataset),
        }
    )


@api_view(["GET"])
def api_records(request, dataset_id):
    dataset = get_dataset(request.user, dataset_id)
    records = filter_state(annotated_records(dataset), request.GET.get("state", ""))
    page = api_page(request, records)
    return JsonResponse(
        {
            "count": page.paginator.count,
            "page": page.number,
            "results": [record_json(record, request.user) for record in page],
        }
    )


def json_payload(request):
    if request.content_type != "application/json":
        raise services.WorkflowError("Send application/json.", status=415)
    if len(request.body) > 10000:
        raise services.WorkflowError("Request body too large.", status=413)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise services.WorkflowError("Malformed JSON.") from exc
    if not isinstance(body, dict) or set(body) - {"label", "comment", "version"}:
        raise services.WorkflowError("Use label, comment, and version fields.")
    if "label" not in body or "version" not in body:
        raise services.WorkflowError("label and version are required.")
    return {"label": body["label"], "comment": body.get("comment", ""), "version": body["version"]}


@api_view(["POST"])
def api_review(request, record_id):
    record = visible_record(request.user, record_id)
    services.submit_review(record, request.user, **json_payload(request))
    record = visible_record(request.user, record_id)
    return JsonResponse(record_json(record, request.user))


@api_view(["POST"])
def api_resolve(request, record_id):
    record = visible_record(request.user, record_id)
    services.resolve_dispute(record, request.user, **json_payload(request))
    record = visible_record(request.user, record_id)
    return JsonResponse(record_json(record, request.user))
