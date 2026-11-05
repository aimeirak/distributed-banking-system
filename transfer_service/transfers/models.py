import uuid

from django.db import models
from django.conf import settings


class Transfer(models.Model):

    class TransferStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RESERVING = "RESERVING", "Reserving Funds"
        RESERVED = "RESERVED", "Funds Reserved"
        CREDITING = "CREDITING", "Crediting Receiver"
        CREDITED = "CREDITED", "Receiver Credited"
        COMMITTING = "COMMITTING", "Committing Debit"
        COMPLETED = "COMPLETED", "Completed"
        COMPENSATING = "COMPENSATING", "Compensating"
        FAILED = "FAILED", "Failed"
        REQUIRES_REVIEW = "REQUIRES_REVIEW", "Requires Review"
        RECOVERING = "RECOVERING", "Recovering Transfer"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    idempotency_key = models.UUIDField(
        unique=True,
        default=uuid.uuid4
    )

    source_account_id = models.UUIDField()

    destination_account_id = models.UUIDField()

    source_account_number = models.CharField(
        max_length=30
    )

    destination_account_number = models.CharField(
        max_length=30
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2
    )

    currency = models.CharField(
        max_length=3,
        default="RWF"
    )

    status = models.CharField(
        max_length=30,
        choices=TransferStatus.choices,
        default=TransferStatus.PENDING
    )

    current_step = models.CharField(
        max_length=50,
        default="CREATED"
    )

    failure_reason = models.TextField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    retry_count = models.PositiveIntegerField(
    default=0
    )

    max_retries = models.PositiveIntegerField(default=10)

    next_retry_at = models.DateTimeField(
        null=True,
        blank=True
    )

    last_error_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # Lease metadata prevents a crashed recovery worker from blocking a transfer forever.
    recovery_started_at = models.DateTimeField(
        null=True,
        blank=True
    )

    recovery_lease_until = models.DateTimeField(
        null=True,
        blank=True
    )

    recovery_token = models.UUIDField(
        null=True,
        blank=True
    )

    # Set when automatic recovery attempts are exhausted and admin action is required.
    dead_lettered_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="initiated_transfers"
)
    recovery_deadline = models.DateTimeField(
    null=True,
    blank=True
)

    class Meta:
        db_table = "transfers"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.id} - {self.status}"


class TransferStep(models.Model):
    class StepStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        COMPENSATED = "COMPENSATED", "Compensated"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name="steps"
    )

    step_name = models.CharField(
        max_length=50
    )

    status = models.CharField(
        max_length=20,
        choices=StepStatus.choices,
        default=StepStatus.PENDING
    )

    attempt_count = models.PositiveIntegerField(
        default=0
    )

    request_data = models.JSONField(
        null=True,
        blank=True
    )

    response_data = models.JSONField(
        null=True,
        blank=True
    )

    error_message = models.TextField(
        null=True,
        blank=True
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = "transfer_steps"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.step_name} - {self.status}"

class UserProfile(models.Model):

    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        BANK_OFFICER = "BANK_OFFICER", "Bank Officer"
        BANK_ADMIN = "BANK_ADMIN", "Bank Administrator"
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Administrator"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile"
    )

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.CUSTOMER
    )

    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    customer_id = models.UUIDField(
    default=uuid.uuid4,
    unique=True,
    editable=False
)

    class Meta:
        db_table = "user_profiles"

    def __str__(self):
        return f"{self.user.username} - {self.role}"