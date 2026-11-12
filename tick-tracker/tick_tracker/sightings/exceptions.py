import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound(*exc.args)
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied(*exc.args)

    response = exception_handler(exc, context)  # DRF's default handling first

    if response is None:
        # Not a DRF-known error -> a real bug. Log the full traceback, hide it from the client.
        view = context.get("view")
        logger.exception("Unhandled error in %s", view.__class__.__name__ if view else "unknown view",
                         exc_info=exc)
        return Response(
            {"error": {"status": 500, "code": "server_error",
                       "message": "An unexpected error occurred."}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    is_simple = isinstance(data, dict) and set(data) == {"detail"}
    body = {
        "status": response.status_code,
        "code": getattr(exc, "default_code", "error"),
        "message": str(data["detail"]) if is_simple else "Invalid request.",
    }
    if not is_simple:
        body["details"] = data  # e.g. {"start_date": ["Enter a valid date."]}

    response.data = {"error": body}
    return response