from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from sightings.models import SyncLog
from sightings.services.client import TickAPIClient, TickAPIError
from sightings.services.importer import import_sightings


class Command(BaseCommand):
    help = "Fetch tick sightings from the Elanco API, clean them and store them."

    def handle(self, *args, **options):
        log = SyncLog.objects.create(status="failed")  # assume failure until proven otherwise

        try:
            raw = TickAPIClient().get_all_sightings()
            result = import_sightings(raw)
        except TickAPIError as exc:
            self._finish(log, error=f"Source API error: {exc}")
            raise CommandError(f"Import failed, source API unavailable: {exc}")
        except Exception as exc:
            self._finish(log, error=f"Unexpected error: {exc}")
            raise

        log.status = "partial" if result.rejected else "success"
        log.fetched = result.fetched
        log.created = result.created
        log.updated = result.updated
        log.rejected = result.rejected
        self._finish(log)

        self.stdout.write(self.style.SUCCESS(
            f"Fetched {result.fetched} | created {result.created} | updated {result.updated} | "
            f"rejected {result.rejected} | duplicates in batch {result.duplicates_in_batch}"
        ))

    @staticmethod
    def _finish(log, error=""):
        log.finished_at = timezone.now()
        log.error_message = error
        log.save()