
from rest_framework.permissions import BasePermission


class HasUserRole(BasePermission):
    """
    Base permission class for checking a user's assigned role.
    """

    allowed_roles = []

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        try:
            profile = request.user.profile
        except Exception:
            return False

        return profile.role in self.allowed_roles


class IsCustomer(HasUserRole):
    allowed_roles = ["CUSTOMER"]


class IsBankOfficer(HasUserRole):
    allowed_roles = ["BANK_OFFICER"]


class IsBankAdmin(HasUserRole):
    allowed_roles = ["BANK_ADMIN"]


class IsSystemAdmin(HasUserRole):
    allowed_roles = ["SYSTEM_ADMIN"]


class IsBankStaff(HasUserRole):
    allowed_roles = ["BANK_OFFICER", "BANK_ADMIN", "SYSTEM_ADMIN"]
