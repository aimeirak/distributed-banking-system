from django.contrib import admin
from .models import LedgerEntry


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):

    list_display = (
        'transfer_id',
        'account',
        'entry_type',
        'amount',
        'created_at',
    )

    search_fields = (
        'transfer_id',
        'account__account_number',
    )

    readonly_fields = (
        'id',
        'account',
        'transfer_id',
        'entry_type',
        'amount',
        'description',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False