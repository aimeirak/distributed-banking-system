
import logging

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from transfers.models import Transfer, TransferStep
from transfers.services.bank_a_client import BankAClient
from transfers.services.bank_b_client import BankBClient

logger = logging.getLogger(__name__)


class TransferRecoveryService:

    def __init__(self):
        self.bank_a = BankAClient()
        self.bank_b = BankBClient()

    def inspect_transfer(self, transfer_id):

        transfer = Transfer.objects.get(id=transfer_id)

        bank_a_status = self.bank_a.get_transfer_status(transfer.id)
        bank_b_status = self.bank_b.get_transfer_status(transfer.id)

        return {
            "transfer_id": str(transfer.id),
            "coordinator_status": transfer.status,
            "bank_a": bank_a_status,
            "bank_b": bank_b_status,
        }

    def recover_transfer(self, transfer_id):

        # Claim the transfer to prevent concurrent recovery.
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

            if transfer.status == Transfer.TransferStatus.RECOVERING:
                return {
                    "message": "Transfer recovery is already in progress.",
                    "status": transfer.status,
                }

            transfer.status = Transfer.TransferStatus.RECOVERING
            transfer.current_step = "RECOVERY_STARTED"
            transfer.save()

        try:
            bank_a = self.bank_a.get_transfer_status(transfer.id)
            bank_b = self.bank_b.get_transfer_status(transfer.id)

            # Verify the actual bank records before taking action.
            self._validate_bank_records(transfer, bank_a, bank_b)

            bank_a_state = bank_a.get("status") if bank_a else None
            bank_b_state = bank_b.get("status") if bank_b else None

            # Case 1: Both banks completed their operations.
            if bank_a_state == "COMMITTED" and bank_b_state == "CREDITED":
                return self._mark_completed(transfer)

            # Case 2: Receiver credited, sender reservation still pending.
            if bank_a_state == "RESERVED" and bank_b_state == "CREDITED":
                self._commit_bank_a(transfer)
                return self._mark_completed(transfer)

            # Case 3: Sender reserved funds, receiver not yet credited.
            if bank_a_state == "RESERVED" and bank_b is None:
                self._credit_bank_b(transfer)
                self._commit_bank_a(transfer)
                return self._mark_completed(transfer)

            # Case 4: Reservation released and no receiver credit exists.
            if bank_a_state == "RELEASED" and bank_b is None:
                return self._mark_failed(
                    transfer,
                    "Bank A reservation was released and Bank B has no credit."
                )

            # Any other combination requires investigation.
            return self._mark_requires_review(
                transfer,
                (
                    f"Unsupported bank state combination. "
                    f"Bank A: {bank_a_state}, Bank B: {bank_b_state}"
                )
            )

        except Exception as exc:
            logger.exception("Transfer recovery failed: %s", transfer.id)

            return self._mark_requires_review(
                transfer,
                f"Recovery operation failed: {str(exc)}"
            )

    def _validate_bank_records(self, transfer, bank_a, bank_b):

        for bank_name, record, expected_account_id in [
            ("Bank A", bank_a, str(transfer.source_account_id)),
            ("Bank B", bank_b, str(transfer.destination_account_id)),
        ]:

            if record is None:
                continue

            if str(record.get("account_id")) != expected_account_id:
                raise ValueError(
                    f"{bank_name} account ID does not match coordinator."
                )

            if Decimal(str(record.get("amount"))) != transfer.amount:
                raise ValueError(
                    f"{bank_name} transaction amount does not match coordinator."
                )

            if record.get("currency") != transfer.currency:
                raise ValueError(
                    f"{bank_name} transaction currency does not match coordinator."
                )

    def _commit_bank_a(self, transfer):

        self._execute_recovery_step(
            transfer,
            "RECOVERY_COMMIT_RESERVATION",
            lambda: self.bank_a.commit_reservation(transfer.id)
        )

    def _credit_bank_b(self, transfer):

        self._execute_recovery_step(
            transfer,
            "RECOVERY_CREDIT_RECEIVER",
            lambda: self.bank_b.credit_account(
                transfer.destination_account_id,
                transfer.id,
                transfer.amount
            )
        )

    def _execute_recovery_step(self, transfer, step_name, action):

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
        step.error_message = None
        step.save()

        try:
            result = action()

            step.status = TransferStep.StepStatus.SUCCESS
            step.response_data = result
            step.completed_at = timezone.now()
            step.save()

            return result

        except Exception as exc:
            step.status = TransferStep.StepStatus.FAILED
            step.error_message = str(exc)
            step.completed_at = timezone.now()
            step.save()
            raise

    def _mark_completed(self, transfer):

        with transaction.atomic():
            transfer = Transfer.objects.select_for_update().get(
                id=transfer.id
            )

            transfer.status = Transfer.TransferStatus.COMPLETED
            transfer.current_step = "COMPLETED"
            transfer.failure_reason = None
            transfer.completed_at = timezone.now()
            transfer.save()

        return {
            "message": "Transfer successfully recovered.",
            "status": transfer.status,
        }

    def _mark_failed(self, transfer, reason):

        transfer.status = Transfer.TransferStatus.FAILED
        transfer.current_step = "FAILED"
        transfer.failure_reason = reason
        transfer.save()

        return {
            "message": reason,
            "status": transfer.status,
        }

    def _mark_requires_review(self, transfer, reason):

        transfer.status = Transfer.TransferStatus.REQUIRES_REVIEW
        transfer.current_step = "REQUIRES_REVIEW"
        transfer.failure_reason = reason
        transfer.save()

        return {
            "message": reason,
            "status": transfer.status,
        }
