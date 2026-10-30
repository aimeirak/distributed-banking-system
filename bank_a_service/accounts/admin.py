from django.contrib import admin

# Register your models here.
from .models import BankAccount, AccountReservation


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = (
        "account_number",
        "customer_name",
        "balance",
        "currency",
        "status",
        "created_at",
    )

    list_filter = ("status", "currency")
    search_fields = ("account_number", "customer_name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AccountReservation)
class AccountReservationAdmin(admin.ModelAdmin):
    list_display = (
        "transfer_id",
        "account",
        "amount",
        "status",
        "created_at",
    )

    list_filter = ("status",)
    search_fields = ("transfer_id", "account__account_number")
    readonly_fields = ("id", "created_at", "updated_at")