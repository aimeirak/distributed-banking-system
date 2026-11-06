import uuid

from django.db import transaction, IntegrityError

from flask import request
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
from django.shortcuts import redirect, render
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, View
from django.views.generic import DetailView
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.shortcuts import redirect

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

@login_required(login_url="login")
def all_transfers_page(request):
        return render(request, "transfers/all_transfers.html")  



class CustomerTransferPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class CustomerTransferListAPIView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request):
        # Only retrieve transfers initiated by the logged-in customer.
        customer_transfers = Transfer.objects.filter(
            created_by=request.user
        )

        # Calculate summary statistics using all customer transfers.
        summary = {
            "total": customer_transfers.count(),
            "completed": customer_transfers.filter(
                status=Transfer.TransferStatus.COMPLETED
            ).count(),
            "processing": customer_transfers.filter(
                status__in=[
                    Transfer.TransferStatus.PENDING,
                    Transfer.TransferStatus.RESERVING,
                    Transfer.TransferStatus.RESERVED,
                    Transfer.TransferStatus.CREDITING,
                    Transfer.TransferStatus.CREDITED,
                    Transfer.TransferStatus.COMMITTING,
                    Transfer.TransferStatus.RECOVERING,
                    Transfer.TransferStatus.COMPENSATING,
                ]
            ).count(),
            "requires_review": customer_transfers.filter(
                status=Transfer.TransferStatus.REQUIRES_REVIEW
            ).count(),
            "failed": customer_transfers.filter(
                status=Transfer.TransferStatus.FAILED
            ).count(),
        }

        queryset = customer_transfers

        # Search by source or destination account number.
        search = request.query_params.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(source_account_number__icontains=search)
                | Q(destination_account_number__icontains=search)
            )

            # Also support searching by transfer UUID.
            try:
                transfer_id = uuid.UUID(search)
                queryset = queryset | customer_transfers.filter(
                    id=transfer_id
                )
            except ValueError:
                pass

        # Filter by transfer status.
        transfer_status = request.query_params.get("status", "").strip()

        if transfer_status:
            valid_statuses = [
                choice[0] for choice in Transfer.TransferStatus.choices
            ]

            if transfer_status not in valid_statuses:
                return Response(
                    {"message": "Invalid transfer status."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            queryset = queryset.filter(status=transfer_status)

        # Filter by creation date.
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        queryset = queryset.order_by("-created_at")

        # Paginate results.
        paginator = CustomerTransferPagination()
        page = paginator.paginate_queryset(queryset, request)

        serializer = TransferCreateSerializer(page, many=True)

        return paginator.get_paginated_response({
            "summary": summary,
            "transfers": serializer.data,
        })

class AccountManagementAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Render the Account Management page.
        """

        try:
            role = request.user.profile.role
        except Exception:
            role = None

        allowed_roles = (
            "CUSTOMER",
            "BANK_OFFICER",
            "BANK_ADMIN",
            "SYSTEM_ADMIN",
        )

        if role not in allowed_roles:
            from django.http import HttpResponseForbidden

            return HttpResponseForbidden(
                "You do not have permission to access Account Management."
            )

        return render(
            request,
            "transfers/account_management.html"
        )


class CustomerManagementView(
    LoginRequiredMixin,
    UserPassesTestMixin,
    ListView
    ):
    model = UserProfile
    template_name = "transfers/customer_management.html"
    context_object_name = "customers"
    paginate_by = 10
    login_url = "login"
    raise_exception = True

    def test_func(self):
        user = self.request.user

        if user.is_superuser:
            return True

        try:
            return user.profile.role == UserProfile.Role.SYSTEM_ADMIN
        except UserProfile.DoesNotExist:
            return False

    def get_queryset(self):
        queryset = (
            UserProfile.objects
            .filter(role=UserProfile.Role.CUSTOMER)
            .select_related("user")
            .order_by("-created_at")
        )

        search = self.request.GET.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(customer_id__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        customers = UserProfile.objects.filter(
            role=UserProfile.Role.CUSTOMER
        )

        context["total_customers"] = customers.count()

        context["active_customers"] = customers.filter(
            user__is_active=True
        ).count()

        context["inactive_customers"] = customers.filter(
            user__is_active=False
        ).count()

        context["search"] = self.request.GET.get("search", "")

        return context

class CustomerDetailView(LoginRequiredMixin,UserPassesTestMixin,DetailView):
    model = UserProfile
    template_name = "transfers/customer_detail.html"
    context_object_name = "customer"
    login_url = "login"

    def test_func(self):
        user = self.request.user

        if user.is_superuser:
            return True

        try:
            return user.profile.role == UserProfile.Role.SYSTEM_ADMIN
        except UserProfile.DoesNotExist:
            return False

    def get_queryset(self):
        return (
            UserProfile.objects
            .filter(role=UserProfile.Role.CUSTOMER)
            .select_related("user")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        customer = self.object
        customer_id = customer.customer_id

        # Customer's transfer history from Transfer Coordinator.
        context["transfers"] = (
            Transfer.objects
            .filter(created_by=customer.user)
            .order_by("-created_at")[:20]
        )

        context["total_transfers"] = Transfer.objects.filter(
            created_by=customer.user
        ).count()

        context["completed_transfers"] = Transfer.objects.filter(
            created_by=customer.user,
            status=Transfer.TransferStatus.COMPLETED
        ).count()

        # Retrieve accounts belonging to this customer from Bank A.
        try:
            bank_a_accounts = BankAClient().get_customer_accounts(
                customer_id
            )

            context["bank_a_accounts"] = bank_a_accounts
            context["bank_a_available"] = True
            context["bank_a_error"] = None

        except requests.RequestException:
            context["bank_a_accounts"] = []
            context["bank_a_available"] = False
            context["bank_a_error"] = (
                "Unable to retrieve accounts from Bank A."
            )

        # Bank B customer-specific account endpoint is not yet available.
        context["bank_b_accounts"] = []
        context["bank_b_available"] = False
        context["bank_b_error"] = (
            "Customer-specific account retrieval is not yet configured "
            "for Bank B."
        )

        return context


class AdminAccountManagementAPIView(APIView):
    permission_classes = [IsSystemAdmin]

    
    def get(self, request):
        customers = UserProfile.objects.filter(
            role=UserProfile.Role.CUSTOMER
        ).select_related("user").order_by("-created_at")

        customer_data = [
            {
                "customer_id": str(profile.customer_id),
                "username": profile.user.username,
                "email": profile.user.email,
                "phone_number": profile.phone_number or "",
            }
            for profile in customers
        ]

        bank_accounts = {
            "BANK_A": [],
            "BANK_B": [],
        }

        bank_status = {
            "BANK_A": "UNAVAILABLE",
            "BANK_B": "UNAVAILABLE",
        }

        errors = {}

        clients = {
            "BANK_A": BankAClient(),
            "BANK_B": BankBClient(),
        }

        for bank_name, client in clients.items():
            try:
                response = client.get_accounts()

                if isinstance(response, dict):
                    response = response.get("accounts", [])

                bank_accounts[bank_name] = [
                    {
                        **account,
                        "bank": bank_name,
                    }
                    for account in response
                ]

                bank_status[bank_name] = "CONNECTED"

            except requests.RequestException as exc:
                errors[bank_name] = str(exc)

        all_accounts = (
            bank_accounts["BANK_A"] +
            bank_accounts["BANK_B"]
        )

        return Response({
            "customers": customer_data,
            "accounts": all_accounts,
            "bank_accounts": bank_accounts,
            "bank_status": bank_status,
            "summary": {
                "total_accounts": len(all_accounts),
                "active_accounts": sum(
                    1 for account in all_accounts
                    if account.get("status") == "ACTIVE"
                ),
                "frozen_accounts": sum(
                    1 for account in all_accounts
                    if account.get("status") == "FROZEN"
                ),
            },
            "errors": errors,
        })


    def post(self, request):
        customer_id = request.data.get("customer_id")
        bank = request.data.get("bank")
        account_number = request.data.get("account_number")
        currency = request.data.get("currency", "RWF")
        initial_balance = request.data.get("initial_balance", "0.00")

        if not all([customer_id, bank, account_number]):
            return Response(
                {"message": "Customer, bank and account number are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if bank not in ["BANK_A", "BANK_B"]:
            return Response(
                {"message": "Invalid bank selected."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            profile = UserProfile.objects.select_related("user").get(
                customer_id=customer_id,
                role=UserProfile.Role.CUSTOMER
            )
        except UserProfile.DoesNotExist:
            return Response(
                {"message": "Customer not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            client = (
                BankAClient() if bank == "BANK_A"
                else BankBClient()
            )

            account = client.create_account(
                account_number=account_number,
                customer_name=profile.user.get_full_name()
                or profile.user.username,
                customer_id=profile.customer_id,
                currency=currency,
                initial_balance=initial_balance
            )

            return Response({
                "message": "Bank account created and linked successfully.",
                "bank": bank,
                "customer": {
                    "customer_id": str(profile.customer_id),
                    "username": profile.user.username,
                },
                "account": account
            }, status=status.HTTP_201_CREATED)

        except requests.RequestException as exc:
            error_detail = (
                exc.response.text
                if exc.response is not None
                else str(exc)
            )

            return Response({
                "message": "Unable to create bank account.",
                "bank": bank,
                "error": error_detail
            }, status=status.HTTP_502_BAD_GATEWAY)
class BanksPageView(LoginRequiredMixin, View):
    login_url = "login"
    def get(self, request):
        return render(request, "transfers/banks.html")


class CustomerBankingAPIView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request):
        customer_id = request.user.profile.customer_id
        accounts = []
        errors = {}

        for bank_code, client_class in (
            ("BANK_A", BankAClient),
            ("BANK_B", BankBClient),
        ):
            try:
                bank_accounts = client_class().get_customer_accounts(
                    customer_id
                )
                if isinstance(bank_accounts, dict):
                    bank_accounts = bank_accounts.get(
                        "results", bank_accounts.get("accounts", [])
                    )
                for account in bank_accounts:
                    account = dict(account)
                    account["bank_code"] = bank_code
                    accounts.append(account)
            except requests.RequestException:
                errors[bank_code] = (
                    f"Could not retrieve {bank_code.replace('_', ' ')} accounts."
                )

        return Response({
            "accounts": accounts,
            "errors": errors,
            "customer": {
                "username": request.user.username,
                "customer_id": str(customer_id),
            },
        }, status=status.HTTP_200_OK)

    def post(self, request):
        customer_id = request.user.profile.customer_id

        bank_code = str(request.data.get("bank_code", "")).upper()
        account_id = request.data.get("account_id")
        transaction_type = str(
            request.data.get("transaction_type", "")
        ).upper()
        amount = request.data.get("amount")
        description = str(request.data.get("description", "")).strip()
        transaction_reference = request.data.get("transaction_reference")

        if bank_code not in ("BANK_A", "BANK_B"):
            return Response(
                {"message": "Select a valid bank account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if transaction_type not in (
            "CASH_DEPOSIT",
            "MOBILE_MONEY_DEPOSIT",
            "CASH_WITHDRAWAL",
        ):
            return Response(
                {"message": "Select a valid transaction type."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount_value = float(amount)
            if amount_value <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            return Response(
                {"message": "Enter an amount greater than zero."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uuid.UUID(str(account_id))
        except (TypeError, ValueError, AttributeError):
            return Response(
                {"message": "Select a valid account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            reference = uuid.UUID(str(transaction_reference))
        except (TypeError, ValueError, AttributeError):
            return Response(
                {"message": "Invalid transaction reference."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client = BankAClient() if bank_code == "BANK_A" else BankBClient()

        try:
            result = client.create_account_transaction(
                transaction_type=transaction_type,
                account_id=account_id,
                customer_id=customer_id,
                transaction_reference=reference,
                amount=amount,
                description=description,
            )
            return Response({
                "message": "Transaction processed successfully.",
                "transaction": result,
            }, status=status.HTTP_200_OK)

        except requests.HTTPError as exc:
            response = exc.response
            try:
                detail = response.json()
            except (ValueError, AttributeError):
                detail = {"message": "The bank rejected the transaction."}
            return Response(
                detail,
                status=response.status_code if response is not None else 502,
            )
        except requests.RequestException:
            return Response(
                {"message": "The selected bank service is currently unavailable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

class MyBankingPageView(LoginRequiredMixin, TemplateView):
    template_name = "transfers/my_banking.html"
    login_url = "login"

    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, "profile"):
            return redirect("dashboard")

        if request.user.profile.role != "CUSTOMER":
            return redirect("dashboard")

        return super().dispatch(request, *args, **kwargs)

class CustomerBankingTransactionsAPIView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request):
        customer_id = request.user.profile.customer_id

        transactions = []
        errors = {}

        for bank_code, client_class in (
            ("BANK_A", BankAClient),
            ("BANK_B", BankBClient),
        ):
            try:
                bank_transactions = (
                    client_class().get_customer_transactions(customer_id)
                )

                if isinstance(bank_transactions, dict):
                    bank_transactions = bank_transactions.get(
                        "results",
                        bank_transactions.get("transactions", [])
                    )

                for transaction in bank_transactions:
                    transaction = dict(transaction)
                    transaction["bank_code"] = bank_code
                    transactions.append(transaction)

            except requests.RequestException:
                errors[bank_code] = (
                    f"Could not retrieve {bank_code} transactions."
                )

        transactions.sort(
            key=lambda item: item.get("created_at", ""),
            reverse=True
        )

        return Response({
            "transactions": transactions,
            "errors": errors,
        }, status=status.HTTP_200_OK)


