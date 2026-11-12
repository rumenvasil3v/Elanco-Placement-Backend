from django.urls import path

from . import views

urlpatterns = [
    path("sightings/", views.SightingListView.as_view(), name="sighting-list"),
    path("sightings/<str:sighting_id>/", views.SightingDetailView.as_view(), name="sighting-detail"),
    path("locations/", views.LocationListView.as_view(), name="location-list"),
    path("species/", views.SpeciesListView.as_view(), name="species-list"),
    path("stats/regions/", views.SightingsByRegionView.as_view(), name="stats-regions"),
    path("stats/trends/", views.SightingTrendsView.as_view(), name="stats-trends"),
    path("health/", views.HealthView.as_view(), name="health"),
]