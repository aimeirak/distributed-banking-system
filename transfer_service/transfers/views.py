from django.db import transaction, IntegrityError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from transfers.models import Transfer
from transfers.serializers import TransferCreateSerializer
from transfers.services.saga_orchestrator import SagaOrchestrator

from transfers.services.recovery_service import TransferRecoveryService


class TransferCreateAPIView(APIView):

    def post(self, request):

        serializer = TransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        idempotency_key = data["idempotency_key"]

        transfer_data = {
            "source_account_id": data["source_account_id"],
            "destination_account_id": data["destination_account_id"],
            "source_account_number": data["source_account_number"],
            "destination_account_number": data["destination_account_number"],
            "amount": data["amount"],
            "currency": data["currency"],
        }

        try:
            with transaction.atomic():

                transfer, created = Transfer.objects.get_or_create(
                    idempotency_key=idempotency_key,
                    defaults=transfer_data
                )

        except IntegrityError:
            # Another concurrent request may have created
            # the same idempotency key.
            transfer = Transfer.objects.get(
                idempotency_key=idempotency_key
            )
            created = False

        if not created:

            # Do not allow an existing idempotency key
            # to be reused for a different transaction.
            same_request = (
                transfer.source_account_id == data["source_account_id"]
                and transfer.destination_account_id == data["destination_account_id"]
                and transfer.source_account_number == data["source_account_number"]
                and transfer.destination_account_number == data["destination_account_number"]
                and transfer.amount == data["amount"]
                and transfer.currency == data["currency"]
            )

            if not same_request:
                return Response(
                    {
                        "message": (
                            "This idempotency key has already been "
                            "used for a different transfer request."
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )

            return Response(
                {
                    "message": "Transfer already exists. Returning existing transfer.",
                    "transfer": TransferCreateSerializer(transfer).data,
                    "failure_reason": transfer.failure_reason,
                    "duplicate_request": True,
                },
                status=status.HTTP_200_OK
            )

        # Only the request that creates the transfer
        # is allowed to start Saga execution.
        orchestrator = SagaOrchestrator()

        transfer = orchestrator.execute_transfer(transfer.id)

        return Response(
            {
                "message": "Transfer processing finished.",
                "transfer": TransferCreateSerializer(transfer).data,
                "failure_reason": transfer.failure_reason,
                "duplicate_request": False,
            },
            status=status.HTTP_200_OK
        )


class TransferDetailAPIView(APIView):

    def get(self, request, transfer_id):

        try:
            transfer = Transfer.objects.get(id=transfer_id)

        except Transfer.DoesNotExist:
            return Response(
                {"message": "Transfer not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = TransferCreateSerializer(transfer)

        steps = transfer.steps.all().values(
            "step_name",
            "status",
            "attempt_count",
            "error_message",
            "started_at",
            "completed_at",
        )

        return Response({
            "transfer": serializer.data,
            "failure_reason": transfer.failure_reason,
            "execution_history": list(steps),
        })

class TransferRecoveryAPIView(APIView):

    def get(self, request, transfer_id):
        try:
            recovery_service = TransferRecoveryService()
            result = recovery_service.inspect_transfer(transfer_id)

            return Response({
                "message": "Transfer inspection completed.",
                "data": result
            }, status=status.HTTP_200_OK)

        except Transfer.DoesNotExist:
            return Response({
                "message": "Transfer not found.",
                "transfer_id": str(transfer_id)
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as exc:
            return Response({
                "message": "Unable to inspect transfer.",
                "error": str(exc)
            }, status=status.HTTP_502_BAD_GATEWAY)

    def post(self, request, transfer_id):
        try:
            recovery_service = TransferRecoveryService()
            result = recovery_service.recover_transfer(transfer_id)

            return Response({
                "message": "Recovery request processed.",
                "data": result
            }, status=status.HTTP_200_OK)

        except Transfer.DoesNotExist:
            return Response({
                "message": "Transfer not found.",
                "transfer_id": str(transfer_id)
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as exc:
            return Response({
                "message": "Unable to recover transfer.",
                "error": str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)