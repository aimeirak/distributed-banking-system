
import logging
import uuid

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from transfers.models import Transfer, TransferStep

from transfers.services.bank_a_client import BankAClient
from transfers.services.bank_b_client import BankBClient


logger = logging.getLogger(__name__)


# A worker owns a recovery lease for two minutes.
RECOVERY_LEASE_DURATION = timedelta(minutes=2)

# Continue automatic recovery for one hour.
RECOVERY_WINDOW = timedelta(hours=1)


class RecoveryLeaseLost(Exception):
    """Raised when this worker no longer owns the recovery lease."""


class RecoveryWindowExpired(Exception):
    """Raised when the automatic recovery window has expired."""


class TransferRecoveryService:

    def __init__(self):
        self.bank_a = BankAClient()
        self.bank_b = BankBClient()

    # ======================================================
    # INSPECT TRANSFER
    # ======================================================

    def inspect_transfer(self, transfer_id):

        transfer = Transfer.objects.get(id=transfer_id)

        bank_a_status = self.bank_a.get_transfer_status(
            transfer.id
        )

        bank_b_status = self.bank_b.get_transfer_status(
            transfer.id
        )

        return {
            "transfer_id": str(transfer.id),
            "coordinator_status": transfer.status,
            "current_step": transfer.current_step,
            "bank_a": bank_a_status,
            "bank_b": bank_b_status,
            "recovery_started_at": transfer.recovery_started_at,
            "recovery_lease_until": transfer.recovery_lease_until,
            "recovery_deadline": transfer.recovery_deadline,
        }

    # ======================================================
    # RECOVER TRANSFER
    # ======================================================

    def recover_transfer(self, transfer_id):

        token = uuid.uuid4()
        now = timezone.now()

        # --------------------------------------------------
        # CLAIM RECOVERY LEASE
        # --------------------------------------------------

        with transaction.atomic():

            transfer = (
                Transfer.objects
                .select_for_update()
                .get(id=transfer_id)
            )

            if transfer.status == Transfer.TransferStatus.COMPLETED:
                return {
                    "message": "Transfer is already completed.",
                    "status": transfer.status,
                }

            if transfer.status == Transfer.TransferStatus.FAILED:
                return {
                    "message": "Transfer has already failed.",
                    "status": transfer.status,
                }

            # Only incomplete transfers can enter recovery.
            allowed_statuses = [
                Transfer.TransferStatus.REQUIRES_REVIEW,
                Transfer.TransferStatus.RESERVED,
                Transfer.TransferStatus.CREDITING,
                Transfer.TransferStatus.CREDITED,
                Transfer.TransferStatus.COMMITTING,
                Transfer.TransferStatus.RESERVING,
                Transfer.TransferStatus.RECOVERING,
            ]

            if transfer.status not in allowed_statuses:
                return {
                    "message": (
                        "Transfer status is not eligible for recovery."
                    ),
                    "status": transfer.status,
                }

            # A worker with a valid lease is already processing it.
            if transfer.status == Transfer.TransferStatus.RECOVERING:

                if (
                    transfer.recovery_lease_until is not None
                    and transfer.recovery_lease_until > now
                ):
                    return {
                        "message": (
                            "Transfer recovery is already owned "
                            "by an active worker."
                        ),
                        "status": transfer.status,
                        "lease_until": transfer.recovery_lease_until,
                    }

            # Initialize the recovery deadline once.
            if transfer.recovery_deadline is None:
                transfer.recovery_deadline = now + RECOVERY_WINDOW

            # Do not continue after the one-hour deadline.
            if transfer.recovery_deadline <= now:

                transfer.status = Transfer.TransferStatus.REQUIRES_REVIEW
                transfer.current_step = "MANUAL_REVIEW_REQUIRED"
                transfer.dead_lettered_at = (
                    transfer.dead_lettered_at or now
                )
                transfer.recovery_started_at = None
                transfer.recovery_lease_until = None
                transfer.recovery_token = None

                transfer.failure_reason = (
                    "Automatic recovery window of one hour expired. "
                    "Administrator review is required."
                )

                transfer.save(
                    update_fields=[
                        "status",
                        "current_step",
                        "dead_lettered_at",
                        "failure_reason",
                        "recovery_deadline",
                        "recovery_started_at",
                        "recovery_lease_until",
                        "recovery_token",
                        "updated_at",
                    ]
                )

                return {
                    "message": "Automatic recovery window expired.",
                    "status": transfer.status,
                }

            # Claim the lease.
            transfer.status = Transfer.TransferStatus.RECOVERING
            transfer.current_step = "RECOVERY_STARTED"
            transfer.recovery_started_at = now
            transfer.recovery_lease_until = (
                now + RECOVERY_LEASE_DURATION
            )
            transfer.recovery_token = token

            transfer.save(
                update_fields=[
                    "status",
                    "current_step",
                    "recovery_started_at",
                    "recovery_lease_until",
                    "recovery_token",
                    "recovery_deadline",
                    "updated_at",
                ]
            )

        # --------------------------------------------------
        # RECONCILE BANK TRANSACTIONS
        # --------------------------------------------------

        try:

            bank_a = self.bank_a.get_transfer_status(
                transfer.id
            )

            bank_b = self.bank_b.get_transfer_status(
                transfer.id
            )

            self._assert_lease(
                transfer.id,
                token
            )

            self._validate_bank_records(
                transfer,
                bank_a,
                bank_b
            )

            bank_a_state = (
                bank_a.get("status") if bank_a else None
            )

            bank_b_state = (
                bank_b.get("status") if bank_b else None
            )

            logger.info(
                (
                    "Transfer %s recovery states: "
                    "Bank A=%s, Bank B=%s"
                ),
                transfer.id,
                bank_a_state,
                bank_b_state,
            )

            # --------------------------------------------------
            # CASE 1: BOTH BANKS COMPLETED
            # --------------------------------------------------

            if (
                bank_a_state == "COMMITTED"
                and bank_b_state == "CREDITED"
            ):
                return self._mark_completed(
                    transfer.id,
                    token
                )

            # --------------------------------------------------
            # CASE 2: BANK B CREDITED, BANK A RESERVED
            # --------------------------------------------------

            if (
                bank_a_state == "RESERVED"
                and bank_b_state == "CREDITED"
            ):

                self._commit_bank_a(
                    transfer,
                    token
                )

                return self._mark_completed(
                    transfer.id,
                    token
                )

            # --------------------------------------------------
            # CASE 3: BANK A RESERVED, BANK B NOT CREDITED
            # --------------------------------------------------

            if (
                bank_a_state == "RESERVED"
                and bank_b_state is None
            ):

                self._credit_bank_b(
                    transfer,
                    token
                )

                self._assert_lease(
                    transfer.id,
                    token
                )

                # Verify that Bank B actually recorded the credit
                # before committing Bank A.
                updated_bank_b = self.bank_b.get_transfer_status(
                    transfer.id
                )

                self._validate_bank_records(
                    transfer,
                    None,
                    updated_bank_b
                )

                updated_bank_b_state = (
                    updated_bank_b.get("status")
                    if updated_bank_b else None
                )

                if updated_bank_b_state != "CREDITED":
                    raise ValueError(
                        "Bank B credit could not be confirmed "
                        "after the credit request."
                    )

                self._commit_bank_a(
                    transfer,
                    token
                )

                return self._mark_completed(
                    transfer.id,
                    token
                )

            # --------------------------------------------------
            # CASE 4: BANK A RELEASED, BANK B NOT CREDITED
            # --------------------------------------------------

            if (
                bank_a_state == "RELEASED"
                and bank_b_state is None
            ):

                return self._mark_failed(
                    transfer.id,
                    token,
                    (
                        "Bank A reservation was released "
                        "and Bank B has no credit."
                    )
                )

            # --------------------------------------------------
            # CASE 5: UNSUPPORTED OR INCONSISTENT BANK STATES
            # --------------------------------------------------

            return self._mark_requires_review(
                transfer.id,
                token,
                (
                    "Unsupported bank state combination. "
                    f"Bank A: {bank_a_state}, "
                    f"Bank B: {bank_b_state}"
                ),
            )

        except RecoveryLeaseLost:

            logger.warning(
                "Recovery lease was lost for transfer %s.",
                transfer.id,
            )

            return {
                "message": (
                    "Recovery lease expired or was claimed "
                    "by another worker."
                ),
                "status": Transfer.TransferStatus.RECOVERING,
            }

        except Exception as exc:

            logger.exception(
                "Transfer recovery failed: %s",
                transfer.id
            )

            try:

                # Temporary errors remain eligible for retry.
                return self._mark_requires_review(
                    transfer.id,
                    token,
                    f"Recovery operation failed: {str(exc)}",
                )

            except RecoveryLeaseLost:

                logger.warning(
                    "Transfer %s lease was lost while "
                    "handling an error.",
                    transfer.id,
                )

                return {
                    "message": (
                        "Recovery lease was lost; "
                        "another worker may retry."
                    ),
                    "status": Transfer.TransferStatus.RECOVERING,
                }

    # ======================================================
    # ASSERT RECOVERY LEASE
    # ======================================================

    def _assert_lease(self, transfer_id, token):

        now = timezone.now()

        transfer = Transfer.objects.filter(
            id=transfer_id,
            status=Transfer.TransferStatus.RECOVERING,
            recovery_token=token,
            recovery_lease_until__gt=now,
            recovery_deadline__gt=now,
        ).first()

        if transfer is None:
            raise RecoveryLeaseLost(
                (
                    "Recovery lease is no longer valid "
                    f"for transfer {transfer_id}."
                )
            )

    # ======================================================
    # VALIDATE BANK RECORDS
    # ======================================================

    def _validate_bank_records(self, transfer, bank_a, bank_b):

        for bank_name, record, expected_account_id in [
            (
                "Bank A",
                bank_a,
                str(transfer.source_account_id),
            ),
            (
                "Bank B",
                bank_b,
                str(transfer.destination_account_id),
            ),
        ]:

            if record is None:
                continue

            if str(record.get("account_id")) != expected_account_id:
                raise ValueError(
                    f"{bank_name} account ID does not match coordinator."
                )

            if Decimal(str(record.get("amount"))) != transfer.amount:
                raise ValueError(
                    f"{bank_name} transaction amount "
                    "does not match coordinator."
                )

            if record.get("currency") != transfer.currency:
                raise ValueError(
                    f"{bank_name} transaction currency "
                    "does not match coordinator."
                )

    # ======================================================
    # COMMIT BANK A RESERVATION
    # ======================================================

    def _commit_bank_a(self, transfer, token):

        self._execute_recovery_step(
            transfer,
            token,
            "RECOVERY_COMMIT_RESERVATION",
            lambda: self.bank_a.commit_reservation(
                transfer.id
            ),
        )

    # ======================================================
    # CREDIT BANK B
    # ======================================================

    def _credit_bank_b(self, transfer, token):

        self._execute_recovery_step(
            transfer,
            token,
            "RECOVERY_CREDIT_RECEIVER",
            lambda: self.bank_b.credit_account(
                transfer.destination_account_id,
                transfer.id,
                transfer.amount,
            ),
        )

    # ======================================================
    # EXECUTE RECOVERY STEP
    # ======================================================

    def _execute_recovery_step(
        self,
        transfer,
        token,
        step_name,
        action,
    ):

        self._assert_lease(
            transfer.id,
            token
        )

        step, _ = TransferStep.objects.get_or_create(
            transfer=transfer,
            step_name=step_name,
            defaults={
                "status": TransferStep.StepStatus.PENDING
            },
        )

        # Do not repeat a recovery step already recorded as successful.
        if step.status == TransferStep.StepStatus.SUCCESS:

            logger.info(
                "Recovery step %s already succeeded for transfer %s.",
                step_name,
                transfer.id,
            )

            return step.response_data

        step.status = TransferStep.StepStatus.IN_PROGRESS
        step.attempt_count += 1
        step.started_at = timezone.now()
        step.completed_at = None
        step.error_message = None

        step.save(
            update_fields=[
                "status",
                "attempt_count",
                "started_at",
                "completed_at",
                "error_message",
            ]
        )

        try:

            result = action()

            self._assert_lease(
                transfer.id,
                token
            )

            step.status = TransferStep.StepStatus.SUCCESS
            step.response_data = result
            step.completed_at = timezone.now()
            step.error_message = None

            step.save(
                update_fields=[
                    "status",
                    "response_data",
                    "completed_at",
                    "error_message",
                ]
            )

            return result

        except Exception as exc:

            step.status = TransferStep.StepStatus.FAILED
            step.error_message = str(exc)
            step.completed_at = timezone.now()

            step.save(
                update_fields=[
                    "status",
                    "error_message",
                    "completed_at",
                ]
            )

            raise

    # ======================================================
    # FINISH TRANSFER WITH STATUS
    # ======================================================

    def _finish_with_status(
        self,
        transfer_id,
        token,
        status,
        current_step,
        message,
        failure_reason=None,
        completed=False,
    ):

        with transaction.atomic():

            transfer = (
                Transfer.objects
                .select_for_update()
                .get(id=transfer_id)
            )

            if (
                transfer.status != Transfer.TransferStatus.RECOVERING
                or transfer.recovery_token != token
                or transfer.recovery_lease_until is None
                or transfer.recovery_lease_until <= timezone.now()
            ):

                raise RecoveryLeaseLost(
                    (
                        "Recovery lease is no longer owned "
                        f"for transfer {transfer_id}."
                    )
                )

            transfer.status = status
            transfer.current_step = current_step
            transfer.failure_reason = failure_reason

            if completed:

                transfer.completed_at = timezone.now()
                transfer.dead_lettered_at = None
                transfer.recovery_deadline = None

            elif status == Transfer.TransferStatus.FAILED:

                transfer.dead_lettered_at = None

            elif current_step == "MANUAL_REVIEW_REQUIRED":

                transfer.dead_lettered_at = timezone.now()

            # Release recovery lease.
            transfer.recovery_started_at = None
            transfer.recovery_lease_until = None
            transfer.recovery_token = None

            transfer.save(
                update_fields=[
                    "status",
                    "current_step",
                    "failure_reason",
                    "completed_at",
                    "dead_lettered_at",
                    "recovery_deadline",
                    "recovery_started_at",
                    "recovery_lease_until",
                    "recovery_token",
                    "updated_at",
                ]
            )

        return {
            "message": message,
            "status": transfer.status,
        }

    # ======================================================
    # MARK COMPLETED
    # ======================================================

    def _mark_completed(self, transfer_id, token):

        return self._finish_with_status(
            transfer_id,
            token,
            Transfer.TransferStatus.COMPLETED,
            "COMPLETED",
            "Transfer successfully recovered.",
            completed=True,
        )

    # ======================================================
    # MARK FAILED
    # ======================================================

    def _mark_failed(self, transfer_id, token, reason):

        return self._finish_with_status(
            transfer_id,
            token,
            Transfer.TransferStatus.FAILED,
            "FAILED",
            reason,
            failure_reason=reason,
        )

    # ======================================================
    # MARK REQUIRES REVIEW
    # ======================================================

    def _mark_requires_review(self, transfer_id, token, reason):

        return self._finish_with_status(
            transfer_id,
            token,
            Transfer.TransferStatus.REQUIRES_REVIEW,
            "RECOVERY_RETRY_PENDING",
            reason,
            failure_reason=reason,
        )

    # ======================================================
    # MARK MANUAL REVIEW AFTER DEADLINE
    # ======================================================

    def mark_manual_review(self, transfer_id):

        now = timezone.now()

        with transaction.atomic():

            transfer = (
                Transfer.objects
                .select_for_update()
                .get(id=transfer_id)
            )

            if transfer.status == Transfer.TransferStatus.COMPLETED:
                return False

            if (
                transfer.recovery_deadline is None
                or transfer.recovery_deadline > now
            ):
                return False

            if (
                transfer.status == Transfer.TransferStatus.RECOVERING
                and transfer.recovery_lease_until is not None
                and transfer.recovery_lease_until > now
            ):
                return False

            transfer.status = Transfer.TransferStatus.REQUIRES_REVIEW
            transfer.current_step = "MANUAL_REVIEW_REQUIRED"
            transfer.dead_lettered_at = now
            transfer.failure_reason = (
                "Automatic recovery window of one hour expired. "
                "Administrator review is required."
            )

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

            return True
