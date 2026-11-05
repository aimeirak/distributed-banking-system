import logging
from datetime import timedelta

from celery import shared_task

from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from transfers.models import Transfer
from transfers.services.recovery_service import TransferRecoveryService


logger = logging.getLogger(__name__)


BASE_RETRY_DELAY_SECONDS = 30
MAX_RETRY_DELAY_SECONDS = 15 * 60
PUBLISH_RETRY_DELAY_SECONDS = 10


# ==========================================================
# RETRY DELAY
# ==========================================================

def calculate_retry_delay(attempt_number):
    """
    Exponential backoff:
    Attempt 1 = 30 seconds, 2 = 60, 3 = 120, etc.
    The delay is capped at 15 minutes.
    """

    attempt_number = max(1, int(attempt_number))
    delay_seconds = BASE_RETRY_DELAY_SECONDS * (2 ** (attempt_number - 1))

    return timedelta(
        seconds=min(delay_seconds, MAX_RETRY_DELAY_SECONDS)
    )

# ==========================================================
# MARK TRANSFER FOR MANUAL REVIEW
# ==========================================================

def mark_for_manual_review(transfer_id, reason=None):
    """
    Stop automatic recovery after the one-hour recovery deadline.

    A live recovery lease is never cleared or overwritten here.
    """

    with transaction.atomic():
        transfer = (
            Transfer.objects
            .select_for_update()
            .filter(id=transfer_id)
            .first()
        )

        if transfer is None:
            return False

        now = timezone.now()

        if transfer.status == Transfer.TransferStatus.COMPLETED:
            if transfer.dead_lettered_at is not None:
                transfer.dead_lettered_at = None
                transfer.save(update_fields=["dead_lettered_at", "updated_at"])
            return False

        # Do not interfere with a worker that still owns a valid lease.
        if (
            transfer.status == Transfer.TransferStatus.RECOVERING
            and transfer.recovery_lease_until is not None
            and transfer.recovery_lease_until > now
        ):
            return False

        # Do not dead-letter a transfer before its recovery window ends.
        if (
            transfer.recovery_deadline is None
            or transfer.recovery_deadline > now
        ):
            return False

        transfer.status = Transfer.TransferStatus.REQUIRES_REVIEW
        transfer.current_step = "MANUAL_REVIEW_REQUIRED"
        transfer.dead_lettered_at = transfer.dead_lettered_at or now

        if reason:
            transfer.failure_reason = reason
        elif not transfer.failure_reason:
            transfer.failure_reason = (
                "The one-hour automatic recovery window expired. "
                "Administrator review is required."
            )

        # Clear only expired/stale recovery ownership.
        transfer.recovery_started_at = None
        transfer.recovery_lease_until = None
        transfer.recovery_token = None

        transfer.save(
            update_fields=[
                "status",
                "current_step",
                "dead_lettered_at",
                "failure_reason",
                "recovery_started_at",
                "recovery_lease_until",
                "recovery_token",
                "updated_at",
            ]
        )

        logger.warning(
            "Transfer %s moved to manual review because its recovery "
            "deadline expired at %s.",
            transfer_id,
            transfer.recovery_deadline,
        )
        return True


# ==========================================================
# CELERY TEST TASK
# ==========================================================

@shared_task
def test_celery_task():
    logger.info("Celery worker is running successfully!")
    return "Celery integration successful"
# ==========================================================
# START A NEW PENDING TRANSFER
# ==========================================================

@shared_task
def start_pending_transfer(transfer_id):
    """
    Start a new transfer through SagaOrchestrator.
    PENDING transfers must not be sent to TransferRecoveryService.
    """

    logger.info("Starting pending transfer %s", transfer_id)

    try:
        from transfers.services.saga_orchestrator import SagaOrchestrator

        transfer = SagaOrchestrator().execute_transfer(transfer_id)

        return {
            "transfer_id": str(transfer_id),
            "status": transfer.status,
        }

    except Exception as exc:
        logger.exception("Could not start pending transfer %s", transfer_id)

        transfer = Transfer.objects.filter(id=transfer_id).first()

        return {
            "transfer_id": str(transfer_id),
            "error": str(exc),
            "status": transfer.status if transfer else "NOT_FOUND",
        }

# ==========================================================
# RECOVER ONE INCOMPLETE TRANSFER
# ==========================================================

@shared_task
def recover_single_transfer(transfer_id):
    """
    Run one recovery attempt.

    The database scheduler owns retry counting and backoff.
    The recovery deadline, not max_retries, controls the one-hour window.
    """

    transfer = Transfer.objects.filter(id=transfer_id).first()

    if transfer is None:
        return {"transfer_id": str(transfer_id), "status": "NOT_FOUND"}

    if transfer.status == Transfer.TransferStatus.COMPLETED:
        return {"transfer_id": str(transfer_id), "status": transfer.status}

    if transfer.status == Transfer.TransferStatus.PENDING:
        return {
            "transfer_id": str(transfer_id),
            "status": transfer.status,
            "message": "Pending transfers must use start_pending_transfer.",
        }

    now = timezone.now()

    # A queued Celery message may arrive after the deadline.
    if (
        transfer.recovery_deadline is None
        or transfer.recovery_deadline <= now
    ):
        mark_for_manual_review(
            transfer_id,
            "The one-hour automatic recovery window expired.",
        )
        transfer.refresh_from_db()
        return {
            "transfer_id": str(transfer_id),
            "status": transfer.status,
            "message": "Recovery deadline has expired.",
        }

    try:
        result = TransferRecoveryService().recover_transfer(transfer_id)

    except Exception as exc:
        logger.exception("Recovery task crashed for transfer %s", transfer_id)
        transfer = Transfer.objects.filter(id=transfer_id).first()

        # Do not mark manual review because retry_count reached max_retries.
        # The scheduler will continue until recovery_deadline.
        return {
            "transfer_id": str(transfer_id),
            "task_error": str(exc),
            "status": transfer.status if transfer else "NOT_FOUND",
        }

    logger.info("Recovery result for transfer %s: %s", transfer_id, result)
    return result


# ==========================================================
# SCHEDULE ONE PENDING TRANSFER
# ==========================================================

def schedule_pending_transfer(transfer_id):
    """
    Schedule a PENDING transfer through SagaOrchestrator.
    The existing max_retries limit remains for initial Saga dispatch.
    """

    with transaction.atomic():
        transfer = (
            Transfer.objects
            .select_for_update()
            .filter(id=transfer_id)
            .first()
        )

        if transfer is None:
            return False

        now = timezone.now()

        if transfer.status != Transfer.TransferStatus.PENDING:
            return False

        if transfer.dead_lettered_at is not None:
            return False

        if transfer.retry_count >= transfer.max_retries:
            return False

        if transfer.next_retry_at is not None and transfer.next_retry_at > now:
            return False

        old_retry_count = transfer.retry_count
        transfer.retry_count += 1
        attempt_number = transfer.retry_count
        transfer.next_retry_at = now + calculate_retry_delay(attempt_number)

        transfer.save(
            update_fields=["retry_count", "next_retry_at", "updated_at"]
        )

    try:
        start_pending_transfer.delay(str(transfer_id))
        logger.info(
            "Scheduled pending transfer %s. Attempt %s.",
            transfer_id,
            attempt_number,
        )
        return True

    except Exception:
        logger.exception("Could not enqueue pending transfer %s", transfer_id)

        Transfer.objects.filter(
            id=transfer_id,
            retry_count=old_retry_count + 1,
        ).update(
            retry_count=old_retry_count,
            next_retry_at=timezone.now() + timedelta(
                seconds=PUBLISH_RETRY_DELAY_SECONDS
            ),
        )
        return False


# ==========================================================
# SCHEDULE ONE INCOMPLETE TRANSFER FOR RECOVERY
# ==========================================================

def schedule_recovery_transfer(transfer_id, retryable_statuses):
    """
    Schedule recovery while the one-hour recovery deadline is still open.

    max_retries is deliberately NOT used as the stopping condition here.
    """

    with transaction.atomic():
        transfer = (
            Transfer.objects
            .select_for_update()
            .filter(id=transfer_id)
            .first()
        )

        if transfer is None:
            return False

        now = timezone.now()

        if transfer.dead_lettered_at is not None:
            return False

        # The deadline must have been initialized by SagaOrchestrator
        # when the first uncertain failure occurred.
        if (
            transfer.recovery_deadline is None
            or transfer.recovery_deadline <= now
        ):
            return False

        if transfer.next_retry_at is not None and transfer.next_retry_at > now:
            return False

        if transfer.status == Transfer.TransferStatus.RECOVERING:
            # A live lease means another worker is already recovering it.
            if (
                transfer.recovery_lease_until is not None
                and transfer.recovery_lease_until > now
            ):
                return False
        elif transfer.status not in retryable_statuses:
            return False

        old_retry_count = transfer.retry_count
        transfer.retry_count += 1
        attempt_number = transfer.retry_count

        next_retry_at = now + calculate_retry_delay(attempt_number)

        # Never schedule beyond the deadline.
        transfer.next_retry_at = min(
            next_retry_at,
            transfer.recovery_deadline,
        )

        transfer.save(
            update_fields=["retry_count", "next_retry_at", "updated_at"]
        )

    try:
        recover_single_transfer.delay(str(transfer_id))

        logger.info(
            "Scheduled recovery for transfer %s. Attempt %s; deadline %s.",
            transfer_id,
            attempt_number,
            transfer.recovery_deadline,
        )
        return True

    except Exception:
        logger.exception("Could not enqueue recovery for transfer %s", transfer_id)

        Transfer.objects.filter(
            id=transfer_id,
            retry_count=old_retry_count + 1,
        ).update(
            retry_count=old_retry_count,
            next_retry_at=timezone.now() + timedelta(
                seconds=PUBLISH_RETRY_DELAY_SECONDS
            ),
        )
        return False


# ==========================================================
# SCAN AND SCHEDULE INCOMPLETE TRANSFERS
# ==========================================================

@shared_task
def scan_incomplete_transfers():
    now = timezone.now()

    # ------------------------------------------------------
    # 1. PENDING TRANSFERS: START THROUGH THE SAGA
    # ------------------------------------------------------

    pending_ids = list(
        Transfer.objects.filter(
            status=Transfer.TransferStatus.PENDING,
            retry_count__lt=models.F("max_retries"),
            dead_lettered_at__isnull=True,
        ).filter(
            Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)
        ).values_list("id", flat=True)
    )

    pending_scheduled_count = 0
    for transfer_id in pending_ids:
        if schedule_pending_transfer(transfer_id):
            pending_scheduled_count += 1

    # ------------------------------------------------------
    # 2. RECOVERY-ELIGIBLE TRANSFERS
    # ------------------------------------------------------

    retryable_statuses = [
        Transfer.TransferStatus.REQUIRES_REVIEW,
        Transfer.TransferStatus.RESERVED,
        Transfer.TransferStatus.CREDITING,
        Transfer.TransferStatus.CREDITED,
        Transfer.TransferStatus.COMMITTING,
        Transfer.TransferStatus.RESERVING,
    ]

    # ------------------------------------------------------
    # 3. EXPIRE RECOVERY WINDOWS
    # ------------------------------------------------------

    expired_query = (
        Q(status__in=retryable_statuses)
        | (
            Q(status=Transfer.TransferStatus.RECOVERING)
            & (
                Q(recovery_lease_until__isnull=True)
                | Q(recovery_lease_until__lte=now)
            )
        )
    )

    expired_ids = list(
        Transfer.objects.filter(
            expired_query,
            recovery_deadline__isnull=False,
            recovery_deadline__lte=now,
            dead_lettered_at__isnull=True,
        ).values_list("id", flat=True)
    )

    dead_lettered_count = 0
    for transfer_id in expired_ids:
        if mark_for_manual_review(transfer_id):
            dead_lettered_count += 1

    # ------------------------------------------------------
    # 4. FIND TRANSFERS STILL INSIDE THEIR RECOVERY WINDOW
    # ------------------------------------------------------

    candidate_query = (
        Q(status__in=retryable_statuses)
        | (
            Q(status=Transfer.TransferStatus.RECOVERING)
            & (
                Q(recovery_lease_until__isnull=True)
                | Q(recovery_lease_until__lte=now)
            )
        )
    )

    candidate_ids = list(
        Transfer.objects.filter(
            candidate_query,
            recovery_deadline__gt=now,
            dead_lettered_at__isnull=True,
        ).filter(
            Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)
        ).values_list("id", flat=True)
    )

    # ------------------------------------------------------
    # 5. SCHEDULE RECOVERY
    # ------------------------------------------------------

    recovery_scheduled_count = 0
    for transfer_id in candidate_ids:
        if schedule_recovery_transfer(transfer_id, retryable_statuses):
            recovery_scheduled_count += 1

    logger.info(
        (
            "Transfer scheduler finished. Pending scheduled=%s, "
            "Recovery scheduled=%s, Moved to manual review=%s"
        ),
        pending_scheduled_count,
        recovery_scheduled_count,
        dead_lettered_count,
    )

    return {
        "pending_scheduled_count": pending_scheduled_count,
        "recovery_scheduled_count": recovery_scheduled_count,
        "dead_lettered_count": dead_lettered_count,
    }
