from datetime import timedelta
import logging
import requests

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from transfers.models import Transfer, TransferStep

from transfers.services.bank_a_client import BankAClient
from transfers.services.bank_b_client import BankBClient


logger = logging.getLogger(__name__)


class SagaOrchestrator:

    def __init__(self):
        self.bank_a = BankAClient()
        self.bank_b = BankBClient()

    def execute_transfer(self, transfer_id):

        # --------------------------------------------------
        # STEP 0: Atomically claim the transfer
        # --------------------------------------------------
        # Only one request or worker can move a PENDING
        # transfer to RESERVING.
        claimed = Transfer.objects.filter(
            id=transfer_id,
            status=Transfer.TransferStatus.PENDING
        ).update(
            status=Transfer.TransferStatus.RESERVING,
            current_step="VERIFY_ACCOUNT_OWNERSHIP",
            updated_at=timezone.now()
        )

        transfer = Transfer.objects.get(id=transfer_id)

        # Already completed or another worker has claimed it.
        if not claimed:
            logger.info(
                "Transfer %s was not claimed. Current status: %s",
                transfer_id,
                transfer.status
            )
            return transfer

        logger.info("Starting Saga for transfer %s", transfer.id)

        # --------------------------------------------------
        # STEP 1: Verify source-account ownership
        # --------------------------------------------------
        try:
            if not transfer.created_by:
                self._mark_failed(
                    transfer,
                    "Transfer has no authenticated customer."
                )
                return transfer

            try:
                profile = transfer.created_by.profile
            except ObjectDoesNotExist:
                self._mark_failed(
                    transfer,
                    "Customer profile does not exist."
                )
                return transfer

            if not profile.customer_id:
                self._mark_failed(
                    transfer,
                    "Customer profile has no customer ID."
                )
                return transfer

            self._execute_step(
                transfer,
                "VERIFY_ACCOUNT_OWNERSHIP",
                lambda: self.bank_a.verify_account_ownership(
                    transfer.source_account_id,
                    profile.customer_id
                )
            )

        except requests.exceptions.HTTPError as exc:

            response = exc.response

            if response is not None and 400 <= response.status_code < 500:
                self._mark_failed(
                    transfer,
                    f"Source account ownership verification rejected: {str(exc)}"
                )
            else:
                self._mark_requires_review(
                    transfer,
                    f"Ownership verification outcome is uncertain: {str(exc)}"
                )

            return transfer

        except requests.exceptions.RequestException as exc:
            self._mark_requires_review(
                transfer,
                f"Could not verify source-account ownership: {str(exc)}"
            )
            return transfer

        except Exception as exc:
            logger.exception(
                "Unexpected ownership verification error for transfer %s",
                transfer.id
            )
            self._mark_failed(
                transfer,
                f"Source account ownership verification failed: {str(exc)}"
            )
            return transfer

        # --------------------------------------------------
        # STEP 2: Reserve funds in Bank A
        # --------------------------------------------------
        try:
            self._update_transfer_status(
                transfer,
                Transfer.TransferStatus.RESERVING,
                "RESERVE_FUNDS"
            )

            self._execute_step(
                transfer,
                "RESERVE_FUNDS",
                lambda: self.bank_a.reserve_funds(
                    transfer.source_account_id,
                    transfer.id,
                    transfer.amount
                )
            )

            self._update_transfer_status(
                transfer,
                Transfer.TransferStatus.RESERVED,
                "FUNDS_RESERVED"
            )

        except requests.exceptions.HTTPError as exc:

            response = exc.response

            # A definite 4xx rejection is treated as a failed
            # reservation, provided Bank A guarantees that
            # rejected requests do not create reservations.
            if response is not None and 400 <= response.status_code < 500:
                self._mark_failed(
                    transfer,
                    f"Bank A rejected funds reservation: {str(exc)}"
                )
            else:
                self._mark_requires_review(
                    transfer,
                    f"Bank A reservation outcome is uncertain: {str(exc)}"
                )

            return transfer

        except requests.exceptions.RequestException as exc:
            # A timeout or connection failure does not prove
            # that Bank A failed to reserve the funds.
            self._mark_requires_review(
                transfer,
                f"Bank A reservation outcome is uncertain: {str(exc)}"
            )
            return transfer

        except Exception as exc:
            logger.exception(
                "Unexpected Bank A reservation error for transfer %s",
                transfer.id
            )
            self._mark_requires_review(
                transfer,
                f"Unexpected Bank A reservation error: {str(exc)}"
            )
            return transfer

        # --------------------------------------------------
        # STEP 3: Credit receiver in Bank B
        # --------------------------------------------------
        try:
            self._update_transfer_status(
                transfer,
                Transfer.TransferStatus.CREDITING,
                "CREDIT_RECEIVER"
            )

            self._execute_step(
                transfer,
                "CREDIT_RECEIVER",
                lambda: self.bank_b.credit_account(
                    transfer.destination_account_id,
                    transfer.id,
                    transfer.amount
                )
            )

            self._update_transfer_status(
                transfer,
                Transfer.TransferStatus.CREDITED,
                "RECEIVER_CREDITED"
            )

        except requests.exceptions.HTTPError as exc:

            response = exc.response

            # A definite 4xx rejection means Bank B rejected
            # the credit without applying it, assuming the
            # Bank B API guarantees this behavior.
            if response is not None and 400 <= response.status_code < 500:
                return self._compensate_reservation(
                    transfer,
                    f"Bank B rejected the credit: {str(exc)}"
                )

            # A 5xx response may be ambiguous.
            self._mark_requires_review(
                transfer,
                f"Uncertain Bank B response: {str(exc)}"
            )
            return transfer

        except requests.exceptions.RequestException as exc:

            # Bank B might have credited the receiver even
            # if the coordinator did not receive its response.
            self._mark_requires_review(
                transfer,
                f"Bank B credit outcome is uncertain: {str(exc)}"
            )
            return transfer

        except Exception as exc:
            logger.exception(
                "Unexpected Bank B credit error for transfer %s",
                transfer.id
            )
            self._mark_requires_review(
                transfer,
                f"Unexpected Bank B error: {str(exc)}"
            )
            return transfer

        # --------------------------------------------------
        # STEP 4: Commit reservation in Bank A
        # --------------------------------------------------
        try:
            self._update_transfer_status(
                transfer,
                Transfer.TransferStatus.COMMITTING,
                "COMMIT_RESERVATION"
            )

            self._execute_step(
                transfer,
                "COMMIT_RESERVATION",
                lambda: self.bank_a.commit_reservation(
                    transfer.id
                )
            )

            # Mark transfer as completed.
            with transaction.atomic():
                transfer.status = Transfer.TransferStatus.COMPLETED
                transfer.current_step = "COMPLETED"
                transfer.completed_at = timezone.now()
                transfer.failure_reason = None

                transfer.save(
                    update_fields=[
                        "status",
                        "current_step",
                        "completed_at",
                        "failure_reason",
                        "updated_at"
                    ]
                )

            logger.info(
                "Transfer %s completed successfully.",
                transfer.id
            )

        except Exception as exc:

            # Bank B has already credited the receiver.
            # Never release Bank A funds at this stage.
            logger.exception(
                "Bank A commit failed for transfer %s",
                transfer.id
            )

            self._mark_requires_review(
                transfer,
                (
                    "Receiver was credited, but Bank A commit failed: "
                    f"{str(exc)}"
                )
            )

        return transfer

    # ======================================================
    # EXECUTE AND TRACK A SAGA STEP
    # ======================================================
    def _execute_step(self, transfer, step_name, action):

        step, created = TransferStep.objects.get_or_create(
            transfer=transfer,
            step_name=step_name,
            defaults={
                "status": TransferStep.StepStatus.PENDING
            }
        )

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
                "error_message"
            ]
        )

        try:
            result = action()

            step.status = TransferStep.StepStatus.SUCCESS
            step.response_data = result
            step.completed_at = timezone.now()
            step.error_message = None

            step.save(
                update_fields=[
                    "status",
                    "response_data",
                    "completed_at",
                    "error_message"
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
                    "completed_at"
                ]
            )

            raise

    # ======================================================
    # UPDATE TRANSFER STATUS
    # ======================================================
    def _update_transfer_status(self, transfer, status, current_step):

        transfer.status = status
        transfer.current_step = current_step

        transfer.save(
            update_fields=[
                "status",
                "current_step",
                "updated_at"
            ]
        )

    # ======================================================
    # COMPENSATE: RELEASE BANK A RESERVATION
    # ======================================================
    def _compensate_reservation(self, transfer, reason):

        self._update_transfer_status(
            transfer,
            Transfer.TransferStatus.COMPENSATING,
            "RELEASE_RESERVATION"
        )

        try:
            self._execute_step(
                transfer,
                "RELEASE_RESERVATION",
                lambda: self.bank_a.release_reservation(
                    transfer.id
                )
            )

            self._mark_failed(
                transfer,
                reason
            )

        except Exception as exc:

            logger.exception(
                "Reservation compensation failed for transfer %s",
                transfer.id
            )

            self._mark_requires_review(
                transfer,
                (
                    f"{reason}. "
                    "Bank A reservation release failed: "
                    f"{str(exc)}"
                )
            )

        return transfer

    # ======================================================
    # MARK TRANSFER AS FAILED
    # ======================================================
    def _mark_failed(self, transfer, reason):

        transfer.status = Transfer.TransferStatus.FAILED
        transfer.failure_reason = reason
        transfer.current_step = "FAILED"

        transfer.save(
            update_fields=[
                "status",
                "failure_reason",
                "current_step",
                "updated_at"
            ]
        )

        logger.warning(
            "Transfer %s marked as FAILED: %s",
            transfer.id,
            reason
        )

    # ======================================================
    # MARK TRANSFER FOR MANUAL REVIEW / RECOVERY
    # ======================================================
    def _mark_requires_review(self, transfer, reason):

        # Start the one-hour recovery window only once.
        if transfer.recovery_deadline is None:
            transfer.recovery_deadline = (
                timezone.now() + timedelta(hours=1)
            )

        transfer.status = Transfer.TransferStatus.REQUIRES_REVIEW
        transfer.failure_reason = reason
        transfer.current_step = "RECOVERY_RETRY_PENDING"

        # Clear any previous dead-letter marker while recovery is allowed.
        transfer.dead_lettered_at = None

        transfer.save(
            update_fields=[
                "status",
                "failure_reason",
                "current_step",
                "recovery_deadline",
                "dead_lettered_at",
                "updated_at"
            ]
        )

        logger.warning(
            "Transfer %s requires recovery. Deadline: %s. Reason: %s",
            transfer.id,
            transfer.recovery_deadline,
            reason
        )