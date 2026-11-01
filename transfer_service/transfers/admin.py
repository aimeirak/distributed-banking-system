from django.contrib import admin
from .models import Transfer, TransferStep


class TransferStepInline(admin.TabularInline):
    model = TransferStep
    extra = 0
    readonly_fields = (
        "step_name",
        "status",
        "attempt_count",
        "request_data",
        "response_data",
        "error_message",
        "started_at",
        "completed_at",
        "created_at",
    )


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "source_account_number",
        "destination_account_number",
        "amount",
        "currency",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "currency",
        "created_at",
    )

    search_fields = (
        "id",
        "source_account_number",
        "destination_account_number",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "completed_at",
    )

    inlines = [TransferStepInline]