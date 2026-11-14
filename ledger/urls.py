from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("datasets/new/", views.dataset_create, name="dataset-create"),
    path("datasets/<uuid:dataset_id>/", views.dataset_detail, name="dataset"),
    path("datasets/<uuid:dataset_id>/import/", views.dataset_import, name="dataset-import"),
    path("datasets/<uuid:dataset_id>/members/", views.members, name="members"),
    path("datasets/<uuid:dataset_id>/assign/", views.assignments, name="assignments"),
    path("datasets/<uuid:dataset_id>/audit/", views.audit_log, name="audit"),
    path("datasets/<uuid:dataset_id>/export/", views.dataset_export, name="export"),
    path("queue/", views.review_queue, name="queue"),
    path("records/<uuid:record_id>/", views.record_detail, name="record"),
    path("api/v1/datasets/", views.api_datasets, name="api-datasets"),
    path("api/v1/datasets/<uuid:dataset_id>/", views.api_dataset, name="api-dataset"),
    path("api/v1/datasets/<uuid:dataset_id>/records/", views.api_records, name="api-records"),
    path("api/v1/records/<uuid:record_id>/reviews/", views.api_review, name="api-review"),
    path("api/v1/records/<uuid:record_id>/resolve/", views.api_resolve, name="api-resolve"),
]
