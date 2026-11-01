from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from transfers.models import Transfer, TransferStep

from transfers.services.bank_a_client import BankAClient
from transfers.services.bank_b_client import BankBClient

import requests
import logging


logger = logging.getLogger(__name__)


class SagaOrchestrator:

    def __init__(self):
        self.bank_a = BankAClient()
        self.bank_b = BankBClient()

    def execute_transfer(self, transfer_id):

        with transaction.atomic():

            transfer = (
                Transfer.objects
                .select_for_update()
                .get(id=transfer_id)
            )

        # Already completed: never execute it again.
        if transfer.status == Transfer.TransferStatus.COMPLETED:
            return transfer

        # Another request or worker has already claimed
        # or processed this transfer.
        if transfer.status != Transfer.TransferStatus.PENDING:
            return transfer

        # Claim the transfer before making external calls.
        transfer.status = Transfer.TransferStatus.RESERVING
        transfer.current_step = "RESERVE_FUNDS"
        transfer.save(
            update_fields=[
                "status",
                "current_step",
                "updated_at"
            ]
        )

        # STEP 1: Reserve funds in Bank A
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

        except Exception as exc:
            self._mark_failed(
                transfer,
                f"Bank A reservation failed: {str(exc)}"
            )
            return transfer

        # STEP 2: Credit receiver in Bank B
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
            # A definitive 4xx response means Bank B rejected
            # the request without applying the credit.
            response = exc.response

            if response is not None and 400 <= response.status_code < 500:
                return self._compensate_reservation(
                    transfer,
                    f"Bank B rejected the credit: {str(exc)}"
                )

            # A 5xx response may be ambiguous. Do not release
            # funds until the credit outcome is reconciled.
            self._mark_requires_review(
                transfer,
                f"Uncertain Bank B response: {str(exc)}"
            )
            return transfer

        except requests.exceptions.RequestException as exc:
            # Timeout or connection failure: Bank B might have
            # credited the receiver even if we did not receive
            # its response.
            self._mark_requires_review(
                transfer,
                f"Bank B outcome is uncertain: {str(exc)}"
            )
            return transfer

        except Exception as exc:
            self._mark_requires_review(
                transfer,
                f"Unexpected Bank B error: {str(exc)}"
            )
            return transfer

        # STEP 3: Commit reservation in Bank A
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

            with transaction.atomic():
                transfer.status = Transfer.TransferStatus.COMPLETED
                transfer.current_step = "COMPLETED"
                transfer.completed_at = timezone.now()
                transfer.failure_reason = None
                transfer.save()

        except Exception as exc:
            # Bank B has already credited the receiver.
            # Never release Bank A funds here.
            self._mark_requires_review(
                transfer,
                f"Receiver was credited, but Bank A commit failed: {str(exc)}"
            )

        return transfer

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

            self._mark_failed(transfer, reason)

        except Exception as exc:
            self._mark_requires_review(
                transfer,
                f"{reason}. Bank A reservation release failed: {str(exc)}"
            )

        return transfer

    def _mark_failed(self, transfer, reason):

        transfer.status = Transfer.TransferStatus.FAILED
        transfer.failure_reason = reason
        transfer.current_step = "FAILED"
        transfer.save()

    def _mark_requires_review(self, transfer, reason):

        transfer.status = Transfer.TransferStatus.REQUIRES_REVIEW
        transfer.failure_reason = reason
        transfer.current_step = "REQUIRES_REVIEW"
        transfer.save()