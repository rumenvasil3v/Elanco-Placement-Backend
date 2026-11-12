from django.db.models import Count, F
from django.db.models.functions import TruncMonth, TruncWeek
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from .filters import SightingFilter
from .models import Location, Sighting, Species
from .serializers import LocationSerializer, SightingSerializer, SpeciesSerializer

from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from .models import Location, Sighting, Species, SyncLog
from .services.client import TickAPIClient

# Query parameters shared by the stats endpoints (for the Swagger docs)
FILTER_PARAMS = [
    OpenApiParameter("start_date", OpenApiTypes.DATE, description="On or after (YYYY-MM-DD)"),
    OpenApiParameter("end_date", OpenApiTypes.DATE, description="On or before (YYYY-MM-DD)"),
    OpenApiParameter("location", OpenApiTypes.STR, description="City name"),
    OpenApiParameter("species", OpenApiTypes.STR, description="Species common name"),
]


def filtered_sightings(request):
    """Apply the same filters as the list endpoint, so stats can be narrowed too."""
    f = SightingFilter(request.query_params, queryset=Sighting.objects.all())
    if not f.is_valid():
        raise ValidationError(f.errors)
    return f.qs


# ---- Sightings ---------------------------------------------------------------

class SightingListView(generics.ListAPIView):
    """List sightings, filterable by date range, location and species."""
    queryset = Sighting.objects.select_related("location", "species")
    serializer_class = SightingSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = SightingFilter
    ordering_fields = ["date"]
    ordering = ["-date"]


class SightingDetailView(generics.RetrieveAPIView):
    """Get a single sighting by its source ID."""
    queryset = Sighting.objects.select_related("location", "species")
    serializer_class = SightingSerializer
    lookup_field = "source_id"
    lookup_url_kwarg = "sighting_id"


# ---- Reference data ----------------------------------------------------------

class LocationListView(generics.ListAPIView):
    """All locations with their total sighting count."""
    queryset = Location.objects.annotate(sighting_count=Count("sightings")).order_by("name")
    serializer_class = LocationSerializer
    pagination_class = None


class SpeciesListView(generics.ListAPIView):
    """All species with their total sighting count."""
    queryset = Species.objects.annotate(sighting_count=Count("sightings")).order_by("name")
    serializer_class = SpeciesSerializer
    pagination_class = None


# ---- Stats -------------------------------------------------------------------

class SightingsByRegionView(APIView):
    @extend_schema(parameters=FILTER_PARAMS, summary="Number of sightings per region")
    def get(self, request):
        qs = filtered_sightings(request)
        rows = (
            qs.values(region=F("location__name"))
            .annotate(count=Count("id"))
            .order_by("-count", "region")
        )
        return Response({"total": qs.count(), "results": list(rows)})


class SightingTrendsView(APIView):
    INTERVALS = {"weekly": TruncWeek, "monthly": TruncMonth}

    @extend_schema(
        parameters=FILTER_PARAMS + [
            OpenApiParameter("interval", OpenApiTypes.STR, enum=["weekly", "monthly"],
                             description="Grouping period (default: monthly)"),
        ],
        summary="Sighting counts over time",
    )
    def get(self, request):
        interval = request.query_params.get("interval", "monthly").lower()
        if interval not in self.INTERVALS:
            raise ValidationError({"interval": "Must be 'weekly' or 'monthly'."})

        trunc = self.INTERVALS[interval]
        rows = (
            filtered_sightings(request)
            .annotate(period=trunc("date"))
            .values("period")
            .annotate(count=Count("id"))
            .order_by("period")
        )
        results = [{"period": r["period"].date().isoformat(), "count": r["count"]} for r in rows]
        return Response({"interval": interval, "results": results})


def _sync_summary(log):
    if log is None:
        return None
    return {
        "status": log.status,
        "started_at": log.started_at,
        "finished_at": log.finished_at,
        "fetched": log.fetched,
        "created": log.created,
        "updated": log.updated,
        "rejected": log.rejected,
        "error_message": log.error_message or None,
    }


class HealthView(APIView):
    @extend_schema(
        summary="Service health and data freshness",
        parameters=[OpenApiParameter("check_source", OpenApiTypes.BOOL,
                                     description="Also ping the external source API")],
    )
    def get(self, request):
        try:
            sighting_count = Sighting.objects.count()
            last_sync = SyncLog.objects.order_by("-started_at").first()
            last_success = (SyncLog.objects.filter(status__in=["success", "partial"])
                            .order_by("-started_at").first())
        except DatabaseError:
            return Response({"status": "error", "database": "unavailable"}, status=503)

        stale_after = timedelta(hours=settings.DATA_STALE_AFTER_HOURS)
        is_stale = (last_success is None
                    or last_success.finished_at is None
                    or timezone.now() - last_success.finished_at > stale_after)
        last_failed = last_sync is not None and last_sync.status == "failed"

        body = {
            "status": "degraded" if (is_stale or last_failed) else "ok",
            "database": "ok",
            "sightings_stored": sighting_count,
            "data_is_stale": is_stale,
            "last_sync": _sync_summary(last_sync),
            "last_successful_sync_at": last_success.finished_at if last_success else None,
        }

        if request.query_params.get("check_source", "").lower() in ("1", "true", "yes"):
            body["source_api"] = "ok" if TickAPIClient().ping() else "unreachable"

        return Response(body, status=200)