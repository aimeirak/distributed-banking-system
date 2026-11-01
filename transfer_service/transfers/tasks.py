import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.db import models, transaction

from transfers.models import Transfer
from transfers.services.recovery_service import TransferRecoveryService

logger = logging.getLogger(__name__)


@shared_task
def test_celery_task():
    logger.info("Celery worker is running successfully!")
    return "Celery integration successful"


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30
)
def recover_single_transfer(self, transfer_id):

    logger.info(
        "Starting automatic recovery for transfer %s",
        transfer_id
    )

    try:
        recovery_service = TransferRecoveryService()

        result = recovery_service.recover_transfer(transfer_id)

        logger.info(
            "Recovery result for transfer %s: %s",
            transfer_id,
            result
        )

        return result

    except Exception as exc:
        logger.exception(
            "Automatic recovery failed for transfer %s",
            transfer_id
        )

        raise self.retry(exc=exc)


@shared_task
def scan_incomplete_transfers():

    now = timezone.now()
    retry_delay = timedelta(seconds=30)

    eligible_statuses = [
        Transfer.TransferStatus.REQUIRES_REVIEW,
        Transfer.TransferStatus.RESERVED,
        Transfer.TransferStatus.CREDITING,
        Transfer.TransferStatus.CREDITED,
        Transfer.TransferStatus.COMMITTING,
        Transfer.TransferStatus.RESERVING,
    ]

    candidates = Transfer.objects.filter(
        status__in=eligible_statuses,
        retry_count__lt=models.F("max_retries"),
    ).filter(
        Q(next_retry_at__isnull=True) |
        Q(next_retry_at__lte=now)
    ).values_list("id", flat=True)

    scheduled_count = 0

    for transfer_id in candidates:

        should_schedule = False

        # Claim a retry slot in the database before publishing.
        with transaction.atomic():

            try:
                transfer = (
                    Transfer.objects
                    .select_for_update()
                    .get(id=transfer_id)
                )
            except Transfer.DoesNotExist:
                continue

            if transfer.status not in eligible_statuses:
                continue

            if transfer.retry_count >= transfer.max_retries:
                continue

            if (
                transfer.next_retry_at is not None
                and transfer.next_retry_at > timezone.now()
            ):
                continue

            transfer.retry_count += 1
            transfer.next_retry_at = timezone.now() + retry_delay

            transfer.save(
                update_fields=[
                    "retry_count",
                    "next_retry_at",
                    "updated_at",
                ]
            )

            should_schedule = True

        if should_schedule:
            try:
                recover_single_transfer.delay(str(transfer_id))
                scheduled_count += 1

                logger.info(
                    "Scheduled recovery for transfer %s. Attempt %s",
                    transfer_id,
                    transfer.retry_count
                )

            except Exception:
                logger.exception(
                    "Could not enqueue recovery for transfer %s",
                    transfer_id
                )

                # Make the transfer eligible for another scheduling attempt.
                Transfer.objects.filter(
                    id=transfer_id,
                    next_retry_at__isnull=False
                ).update(next_retry_at=timezone.now())

    logger.info(
        "Recovery scheduler finished. Scheduled %s transfers.",
        scheduled_count
    )

    return {
        "scheduled_count": scheduled_count
    }