
import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class IsInternalService(BasePermission):

    message = "Access denied. Trusted service authentication required."

    def has_permission(self, request, view):
        expected_token = settings.BANK_INTERNAL_SERVICE_TOKEN
        provided_token = request.headers.get("X-Service-Token", "")

        if not expected_token or not provided_token:
            return False

        return hmac.compare_digest(
            expected_token,
            provided_token
        )

class IsAccountAdministrator(BasePermission):
    message = "Account administration access required."

    def has_permission(self, request, view):
        expected_token = getattr(
            settings,
            "BANK_ACCOUNT_ADMIN_TOKEN",
            ""
        )

        provided_token = request.headers.get(
            "X-Account-Admin-Token",
            ""
        )

        if not expected_token or not provided_token:
            return False

        return hmac.compare_digest(
            expected_token,
            provided_token
        )