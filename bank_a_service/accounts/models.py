import uuid

from django.db import models

# Create your models here.
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


class AccountReservation(models.Model):
    class ReservationStatus(models.TextChoices):
        RESERVED = "RESERVED", "Reserved"
        COMMITTED = "COMMITTED", "Committed"
        RELEASED = "RELEASED", "Released"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="reservations"
    )

    transfer_id = models.UUIDField(unique=True)

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.RESERVED
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "account_reservations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.transfer_id} - {self.amount}"
