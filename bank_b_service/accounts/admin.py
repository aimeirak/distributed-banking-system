from django.contrib import admin
from .models import BankAccount


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):

    list_display = (
        'account_number',
        'customer_name',
        'balance',
        'currency',
        'status',
        'created_at',
    )

    list_filter = ('status', 'currency')

    search_fields = (
        'account_number',
        'customer_name',
    )

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
    )