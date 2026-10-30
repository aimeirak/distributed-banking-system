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

    