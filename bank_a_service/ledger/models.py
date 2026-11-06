from django.db import models

import uuid
from accounts.models import BankAccount

# Create your models here.
class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        RESERVATION = "RESERVATION", "Reservation"
        DEBIT = "DEBIT", "Debit"
        RELEASE = "RELEASE", "Release"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="ledger_entries"
    )

    transfer_id = models.UUIDField()

    entry_type = models.CharField(
        max_length=20,
        choices=EntryType.choices
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2
    )

    description = models.CharField(
        max_length=255,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_ledger_entries"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["transfer_id", "entry_type"],
                name="unique_bank_transfer_ledger_entry"
            )
        ]

    def __str__(self):
        return f"{self.entry_type} - {self.amount}"

class AccountTransaction(models.Model):
    class TransactionType(models.TextChoices):
        CASH_DEPOSIT = "CASH_DEPOSIT", "Cash deposit"
        MOBILE_MONEY_DEPOSIT = "MOBILE_MONEY_DEPOSIT", "Mobile money deposit"
        CASH_WITHDRAWAL = "CASH_WITHDRAWAL", "Cash withdrawal"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="account_transactions",
    )

    transaction_reference = models.UUIDField(unique=True)
    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    balance_before = models.DecimalField(max_digits=18, decimal_places=2)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2)

    # UUID of the customer whose account is being operated on.
    customer_id = models.UUIDField(db_index=True)

    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_transactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "-created_at"]),
            models.Index(fields=["customer_id", "-created_at"]),
            models.Index(fields=["transaction_type", "-created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.transaction_type} - {self.transaction_reference} "
            f"- {self.amount} {self.currency}"
        )
    