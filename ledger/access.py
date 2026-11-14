from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Dataset, Membership


def visible_datasets(user):
    if user.is_superuser:
        return Dataset.objects.all()
    return Dataset.objects.filter(memberships__user=user)


def get_dataset(user, dataset_id):
    return get_object_or_404(visible_datasets(user), pk=dataset_id)


def role_for(user, dataset):
    if user.is_superuser:
        return Membership.Role.MANAGER
    return (
        Membership.objects.filter(dataset=dataset, user=user).values_list("role", flat=True).first()
    )


def require_role(user, dataset, *roles):
    role = role_for(user, dataset)
    if role not in roles:
        raise PermissionDenied("Your dataset role does not allow this action.")
    return role
