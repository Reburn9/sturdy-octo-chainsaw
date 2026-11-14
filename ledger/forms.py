from django import forms
from django.contrib.auth import get_user_model

from .models import Membership


class DatasetForm(forms.Form):
    name = forms.CharField(max_length=120, label="Dataset name")
    description = forms.CharField(
        max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    labels = forms.CharField(
        help_text="Comma-separated labels, for example: positive, neutral, negative",
        widget=forms.TextInput(attrs={"placeholder": "positive, neutral, negative"}),
    )
    required_reviews = forms.IntegerField(
        min_value=2,
        max_value=5,
        initial=2,
        help_text="Distinct reviewers required for each record (2–5).",
    )

    def clean_labels(self):
        labels = [label.strip() for label in self.cleaned_data["labels"].split(",")]
        if not 2 <= len(labels) <= 12 or len(set(labels)) != len(labels):
            raise forms.ValidationError("Provide 2–12 unique, nonempty labels.")
        if any(not label or len(label) > 60 for label in labels):
            raise forms.ValidationError("Each label must contain 1–60 characters.")
        return labels


class ImportForm(forms.Form):
    file = forms.FileField(
        label="CSV or JSONL file",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".csv,.jsonl",
                "aria-describedby": "import-help",
            }
        ),
    )


class AssignmentForm(forms.Form):
    reviewer = forms.ModelChoiceField(queryset=get_user_model().objects.none())
    count = forms.IntegerField(min_value=1, max_value=100, initial=10)

    def __init__(self, *args, dataset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reviewer"].queryset = (
            get_user_model()
            .objects.filter(
                membership__dataset=dataset,
                is_active=True,
                membership__role__in=[Membership.Role.MANAGER, Membership.Role.REVIEWER],
            )
            .order_by("username")
        )


class MemberForm(forms.Form):
    username = forms.CharField(max_length=150)
    role = forms.ChoiceField(choices=Membership.Role.choices)


class ReviewForm(forms.Form):
    label = forms.ChoiceField(widget=forms.RadioSelect)
    comment = forms.CharField(
        max_length=2000,
        required=False,
        label="Review note",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "What supports your decision?"}),
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, dataset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].choices = [(label, label) for label in dataset.labels]
