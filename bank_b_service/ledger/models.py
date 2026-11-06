from django.db import models
# Create your models here.
import uuid

from django.db import models
from accounts.models import BankAccount


class LedgerEntry(models.Model):

    class EntryType(models.TextChoices):
        CREDIT = "CREDIT", "Interbank Credit"

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

    transfer_id = models.UUIDField(unique=True)

    entry_type = models.CharField(
        max_length=20,
        choices=EntryType.choices,
        default=EntryType.CREDIT
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

    def __str__(self):
        return f"{self.transfer_id} - {self.amount}"


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
    