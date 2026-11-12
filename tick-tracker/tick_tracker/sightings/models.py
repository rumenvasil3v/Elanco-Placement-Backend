from django.db import models

# Create your models here.


class Species(models.Model):
    name = models.CharField(max_length=150, unique=True)
    latin_name = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name_plural = 'species'
        ordering = ['name']

    def __str__(self):
        return self.name


class Location(models.Model):
    name = models.CharField(max_length=100, unique=True)          # canonical: "London"
    
    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Sighting(models.Model):
    source_id = models.CharField(max_length=64, unique=True)
    date = models.DateTimeField(db_index=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='sightings')
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name="sightings")
    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        indexes = [models.Index(fields=["location", "date"])]   # "London between X and Y"

    def __str__(self):
        return f"{self.species} in {self.location} on {self.date:%Y-%m-%d}"


class RejectedRecord(models.Model):
    """Raw records that failed validation, kept with the reason."""
    source_id = models.CharField(max_length=64, blank=True)
    raw_data = models.JSONField()
    reason = models.TextField()
    rejected_at = models.DateTimeField(auto_now_add=True)

class SyncLog(models.Model):
    STATUS_CHOICES = [("success", "Success"), ("partial", "Partial"), ("failed", "Failed")]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    fetched = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    rejected = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)