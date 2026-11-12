from rest_framework import serializers

from .models import Location, Sighting, Species


class SightingSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="source_id")
    location = serializers.CharField(source="location.name")
    species = serializers.CharField(source="species.name")
    latin_name = serializers.CharField(source="species.latin_name")

    class Meta:
        model = Sighting
        fields = ["id", "date", "location", "species", "latin_name"]


class LocationSerializer(serializers.ModelSerializer):
    sighting_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Location
        fields = ["name", "sighting_count"]


class SpeciesSerializer(serializers.ModelSerializer):
    sighting_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Species
        fields = ["name", "latin_name", "sighting_count"]