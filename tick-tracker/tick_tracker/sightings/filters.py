import django_filters
from django import forms

from .models import Sighting


class SightingFilterForm(forms.Form):
    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError("start_date must be on or before end_date.")
        return cleaned


class SightingFilter(django_filters.FilterSet):
    start_date = django_filters.DateFilter(
        field_name="date", lookup_expr="date__gte",
        help_text="Include sightings on or after this date (YYYY-MM-DD).",
    )
    end_date = django_filters.DateFilter(
        field_name="date", lookup_expr="date__lte",
        help_text="Include sightings on or before this date (YYYY-MM-DD).",
    )
    location = django_filters.CharFilter(
        field_name="location__name", lookup_expr="iexact",
        help_text="City name, case-insensitive (e.g. london).",
    )
    species = django_filters.CharFilter(
        field_name="species__name", lookup_expr="iexact",
        help_text="Species common name, case-insensitive.",
    )

    class Meta:
        model = Sighting
        fields = []
        form = SightingFilterForm