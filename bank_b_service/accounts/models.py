from django.db import models
# Create your models here.
import uuid


class BankAccount(models.Model):

    class AccountStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        FROZEN = "FROZEN", "Frozen"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    account_number = models.CharField(
        max_length=30,
        unique=True
    )

    customer_name = models.CharField(max_length=150)

    currency = models.CharField(
        max_length=3,
        default="RWF"
    )

    balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bank_accounts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.account_number} - {self.customer_name}"