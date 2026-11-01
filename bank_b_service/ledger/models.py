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