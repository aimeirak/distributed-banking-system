from django.db import transaction, IntegrityError

import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser

from transfers.models import Transfer, UserProfile
from transfers.serializers import CustomerRegistrationSerializer, TransferCreateSerializer
from transfers.services.saga_orchestrator import SagaOrchestrator

from transfers.services.recovery_service import TransferRecoveryService
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsCustomer, IsSystemAdmin
from transfers.services.bank_a_client import BankAClient
from transfers.services.bank_b_client import BankBClient
from transfers.permissions import IsCustomer
from django.contrib.auth.decorators import login_required
import json
from decimal import Decimal

from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone

from django.shortcuts import render

class TransferCreateAPIView(APIView):
    # Temporary safe default: account ownership checks are not yet implemented.
    # permission_classes = [IsAdminUser]
    permission_classes = [IsCustomer]

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
             "created_by": request.user,
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
            if transfer.created_by_id != request.user.id:
                return Response(
                    {"message": "Transfer not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

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
    permission_classes = [IsAuthenticated]

    def get(self, request, transfer_id):

        try:
            transfer = Transfer.objects.get(id=transfer_id)

        except Transfer.DoesNotExist:
            return Response(
                {"message": "Transfer not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check whether the user is allowed to view this transfer
        if (
            not request.user.is_staff
            and transfer.created_by_id != request.user.id
        ):
            return Response(
                {"message": "Transfer not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Serialize transfer details
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
    # Recovery inspection and execution are restricted to staff users.
    permission_classes = [IsSystemAdmin]


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


class CustomerRegistrationAPIView(APIView):
    permission_classes = [AllowAny]
    @transaction.atomic
    def post(self, request):
        serializer = CustomerRegistrationSerializer( data=request.data)

        if serializer.is_valid():
            user = serializer.save()

            profile = user.profile

            return Response(
                {
                    "message": "Customer registered successfully.",
                    "customer": {
                        "user_id": user.id,
                        "customer_id": str(profile.customer_id),
                        "username": user.username,
                        "email": user.email,
                        "role": profile.role,
                    }
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class CustomerProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, created = UserProfile.objects.get_or_create(
            user=request.user
        )

        return Response({
            "user_id": request.user.id,
            "customer_id": str(profile.customer_id),
            "username": request.user.username,
            "email": request.user.email,
            "role": profile.role,
            "phone_number": profile.phone_number,
        })
    
@login_required(login_url="login")
def dashboard(request):
    year = timezone.localdate().year

    processing_statuses = [
        Transfer.TransferStatus.PENDING,
        Transfer.TransferStatus.RESERVING,
        Transfer.TransferStatus.RESERVED,
        Transfer.TransferStatus.CREDITING,
        Transfer.TransferStatus.CREDITED,
        Transfer.TransferStatus.COMMITTING,
        Transfer.TransferStatus.RECOVERING,
    ]

    month_labels = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    # Monthly counts for the current calendar year.
    monthly_rows = (
        Transfer.objects
        .filter(created_at__year=year)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            completed=Count(
                "id",
                filter=Q(status=Transfer.TransferStatus.COMPLETED),
            ),
            requires_review=Count(
                "id",
                filter=Q(status=Transfer.TransferStatus.REQUIRES_REVIEW),
            ),
        )
        .order_by("month")
    )

    monthly_by_number = {
        row["month"].month: row for row in monthly_rows if row["month"]
    }

    monthly_activity = [
        {
            "completed": monthly_by_number.get(month, {}).get("completed", 0),
            "requires_review": monthly_by_number.get(month, {}).get("requires_review", 0),
        }
        for month in range(1, 13)
    ]

    # Status distribution.
    status_labels = ["Completed", "Processing", "Requires Review", "Failed"]
    status_values = [
        Transfer.objects.filter(
            status=Transfer.TransferStatus.COMPLETED
        ).count(),
        Transfer.objects.filter(status__in=processing_statuses).count(),
        Transfer.objects.filter(
            status=Transfer.TransferStatus.REQUIRES_REVIEW
        ).count(),
        Transfer.objects.filter(status="FAILED").count(),
    ]

    # Monthly transfer value grouped by currency to avoid mixing currencies.
    amount_rows = list(
        Transfer.objects
        .filter(created_at__year=year)
        .exclude(status="FAILED")
        .annotate(month=TruncMonth("created_at"))
        .values("month", "currency")
        .annotate(total_amount=Sum("amount"))
        .order_by("month", "currency")
    )

    currencies = sorted({
        row["currency"] for row in amount_rows if row["currency"]
    })

    monthly_value_datasets = []
    for currency in currencies:
        amounts_by_month = {}
        for row in amount_rows:
            if row["currency"] == currency and row["month"]:
                amounts_by_month[row["month"].month] = float(
                    row["total_amount"] or Decimal("0")
                )

        monthly_value_datasets.append({
            "label": currency,
            "data": [
                amounts_by_month.get(month, 0)
                for month in range(1, 13)
            ],
            "fill": False,
            "tension": 0.3,
        })

    context = {
        "total_transfers": Transfer.objects.count(),
        "completed_transfers": status_values[0],
        "pending_transfers": status_values[1],
        "review_transfers": status_values[2],
        "recent_transfers": Transfer.objects.order_by("-created_at")[:10],

        "chart_month_labels_json": json.dumps(month_labels),
        "monthly_activity_json": json.dumps(monthly_activity),
        "status_labels_json": json.dumps(status_labels),
        "status_values_json": json.dumps(status_values),
        "monthly_value_datasets_json": json.dumps(monthly_value_datasets),
    }

    return render(request, "transfers/index.html", context)

class CustomerSourceAccountsAPIView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request):
        try:
            customer_id = request.user.profile.customer_id

            accounts = BankAClient().get_customer_accounts(
                customer_id
            )

            return Response({
                "accounts": accounts
            }, status=status.HTTP_200_OK)

        except requests.RequestException:
            return Response(
                {"message": "Unable to retrieve Bank A accounts."},
                status=status.HTTP_502_BAD_GATEWAY
            )


class VerifyDestinationAccountAPIView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request):
        account_number = request.query_params.get(
            "account_number", ""
        ).strip()

        if not account_number:
            return Response(
                {"message": "Please enter the receiver account number."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            account = BankBClient().lookup_account(
                account_number
            )

            if account is None:
                return Response(
                    {"verified": False,
                     "message": "Receiver account was not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                "verified": True,
                "account": account
            }, status=status.HTTP_200_OK)

        except requests.RequestException:
            return Response(
                {"message": "Unable to verify receiver account with Bank B."},
                status=status.HTTP_502_BAD_GATEWAY
            )

@login_required(login_url="login")
def new_transfer_page(request):
    return render(request, "transfers/transfer.html")     
