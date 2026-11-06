from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


from ledger.models import AccountTransaction
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers

from accounts.serializers import AccountTransactionHistorySerializer, AccountTransactionRequestSerializer, LinkAccountOwnershipSerializer
from accounts.services import deposit_mobile_money, link_account_to_customer
from rest_framework.permissions import IsAdminUser
from accounts.permissions import (
    IsInternalService,
    IsAccountAdministrator
)
from accounts.serializers import VerifyAccountOwnershipSerializer
from accounts.services import verify_account_ownership

from accounts.models import BankAccount
from accounts.serializers import (
    BankAccountSerializer,
    ReserveFundsSerializer,
    TransferActionSerializer
)

from accounts.services import (
    create_account,
    get_account_balance,
    reserve_funds,
    commit_reservation,
    release_reservation,
    get_transfer_status
)

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from accounts.serializers import AccountTransactionRequestSerializer
from accounts.services import deposit_cash, deposit_mobile_money, withdraw_cash

def _account_transaction_response(transaction, created=True):
    return Response(
        {
            "id": str(transaction.id),
            "transaction_reference": str(transaction.transaction_reference),
            "account_id": str(transaction.account_id),
            "account_number": transaction.account.account_number,
            "customer_id": str(transaction.customer_id),
            "transaction_type": transaction.transaction_type,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "balance_before": str(transaction.balance_before),
            "balance_after": str(transaction.balance_after),
            "description": transaction.description,
            "created_at": transaction.created_at.isoformat(),
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )

class BankAccountListCreateAPIView(APIView):
    permission_classes = [IsInternalService]
    def get(self, request):
        accounts = BankAccount.objects.all()
        serializer = BankAccountSerializer(accounts, many=True)

        return Response(serializer.data)

    
    def post(self, request):
        serializer = BankAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            account = create_account(
                account_number=serializer.validated_data['account_number'],
                customer_name=serializer.validated_data['customer_name'],
                currency=serializer.validated_data.get('currency', 'RWF'),
                initial_balance=serializer.validated_data.get('balance', 0),
                owner_customer_id=request.data.get("owner_customer_id")
            )

            return Response(
                BankAccountSerializer(account).data,
                status=status.HTTP_201_CREATED
            )

        except DjangoValidationError as exc:
            return Response(
                {'error': exc.messages},
                status=status.HTTP_400_BAD_REQUEST
            )



class AccountBalanceAPIView(APIView):
    permission_classes = [IsInternalService]

    def get(self, request, account_id):
        try:
            balance = get_account_balance(account_id)
            return Response(balance)

        except Exception as exc:
            from django.http import Http404

            if isinstance(exc, Http404):
                return Response(
                    {'error': 'Bank account not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            raise


class ReserveFundsAPIView(APIView):
    permission_classes = [IsInternalService]
    def post(self, request):
        serializer = ReserveFundsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reservation = reserve_funds(
                account_id=serializer.validated_data['account_id'],
                transfer_id=serializer.validated_data['transfer_id'],
                amount=serializer.validated_data['amount']
            )

            return Response({
                'message': 'Funds reserved successfully.',
                'transfer_id': str(reservation.transfer_id),
                'account_id': str(reservation.account_id),
                'amount': str(reservation.amount),
                'status': reservation.status
            }, status=status.HTTP_200_OK)

        except DjangoValidationError as exc:
            return Response(
                {'error': exc.messages},
                status=status.HTTP_400_BAD_REQUEST
            )


class CommitReservationAPIView(APIView):
    permission_classes = [IsInternalService]
    def post(self, request):
        serializer = TransferActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reservation = commit_reservation(
                serializer.validated_data['transfer_id']
            )

            return Response({
                'message': 'Reservation committed successfully.',
                'transfer_id': str(reservation.transfer_id),
                'status': reservation.status
            })

        except DjangoValidationError as exc:
            return Response(
                {'error': exc.messages},
                status=status.HTTP_400_BAD_REQUEST
            )


class ReleaseReservationAPIView(APIView):
    permission_classes = [IsInternalService]
    def post(self, request):
        serializer = TransferActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reservation = release_reservation(
                serializer.validated_data['transfer_id']
            )

            return Response({
                'message': 'Reservation released successfully.',
                'transfer_id': str(reservation.transfer_id),
                'status': reservation.status
            })

        except DjangoValidationError as exc:
            return Response(
                {'error': exc.messages},
                status=status.HTTP_400_BAD_REQUEST
            )

class TransferStatusAPIView(APIView):
    permission_classes = [IsInternalService]
    def get(self, request, transfer_id):

        try:
            result = get_transfer_status(transfer_id)

            return Response(
                {
                    "message": "Transfer status retrieved successfully.",
                    "data": result
                },
                status=status.HTTP_200_OK
            )

        except Exception as exc:
            from django.http import Http404

            if isinstance(exc, Http404):
                return Response(
                    {
                        "message": "Transfer reservation not found.",
                        "transfer_id": str(transfer_id)
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

            raise


class LinkAccountOwnershipAPIView(APIView):
    permission_classes = [IsAccountAdministrator]
    def post(self, request):
        serializer = LinkAccountOwnershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            account = link_account_to_customer(
                account_id=serializer.validated_data["account_id"],
                customer_id=serializer.validated_data["customer_id"]
            )

            return Response({
                "message": "Account linked successfully.",
                "account_id": str(account.id),
                "account_number": account.account_number,
                "owner_customer_id": str(account.owner_customer_id)
            }, status=status.HTTP_200_OK)

        except DjangoValidationError as exc:
            return Response(
                {"error": exc.messages},
                status=status.HTTP_400_BAD_REQUEST
            )

class VerifyAccountOwnershipAPIView(APIView):
    permission_classes = [IsInternalService]

    def post(self, request):
        serializer = VerifyAccountOwnershipSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            account = verify_account_ownership(
                account_id=serializer.validated_data["account_id"],
                customer_id=serializer.validated_data["customer_id"]
            )

            return Response({
                "verified": True,
                "account_id": str(account.id),
                "account_number": account.account_number,
                "customer_id": str(account.owner_customer_id),
                "currency": account.currency
            })

        except DjangoValidationError as exc:
            return Response(
                {
                    "verified": False,
                    "message": exc.messages
                },
                status=status.HTTP_403_FORBIDDEN
            )

class CustomerBankAccountsAPIView(APIView):
    permission_classes = [IsInternalService]

    def get(self, request, customer_id):
        accounts = BankAccount.objects.filter(
            owner_customer_id=customer_id,
            status=BankAccount.AccountStatus.ACTIVE
        )

        serializer = BankAccountSerializer(accounts, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


    def _account_transaction_response(account_transaction, created):
        return Response(
            {
                "message": (
                    "Account transaction completed successfully."
                    if created else
                    "This transaction was already processed."
                ),
                "created": created,
                "data": {
                    "id": str(account_transaction.id),
                    "transaction_reference": str(account_transaction.transaction_reference),
                    "transaction_type": account_transaction.transaction_type,
                    "account_id": str(account_transaction.account_id),
                    "account_number": account_transaction.account.account_number,
                    "customer_id": str(account_transaction.customer_id),
                    "amount": str(account_transaction.amount),
                    "currency": account_transaction.currency,
                    "balance_before": str(account_transaction.balance_before),
                    "balance_after": str(account_transaction.balance_after),
                    "description": account_transaction.description,
                    "created_at": account_transaction.created_at.isoformat(),
                },
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

class CashDepositAPIView(APIView):
    authentication_classes = []
    permission_classes = [IsInternalService]

    def post(self, request):
        serializer = AccountTransactionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result, created = deposit_cash(**serializer.validated_data)
            return _account_transaction_response(result, created)
        except DjangoValidationError as exc:
            return Response(
                {"message": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )


class MobileMoneyDepositAPIView(APIView):
    authentication_classes = []
    permission_classes = [IsInternalService]

    def post(self, request):
        serializer = AccountTransactionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result, created = deposit_mobile_money(**serializer.validated_data)
            return _account_transaction_response(result, created)
        except DjangoValidationError as exc:
            return Response(
                {"message": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )


class CashWithdrawalAPIView(APIView):
    authentication_classes = []
    permission_classes = [IsInternalService]

    def post(self, request):
        serializer = AccountTransactionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result, created = withdraw_cash(**serializer.validated_data)
            return _account_transaction_response(result, created)
        except DjangoValidationError as exc:
            return Response(
                {"message": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

class CustomerAccountTransactionsAPIView(APIView):
    authentication_classes = []
    permission_classes = [IsInternalService]

    def get(self, request, customer_id):
        transactions = (
            AccountTransaction.objects
            .filter(customer_id=customer_id)
            .select_related("account")
            .order_by("-created_at")
        )

        serializer = AccountTransactionHistorySerializer(
            transactions,
            many=True
        )

        return Response({
            "transactions": serializer.data
        }, status=status.HTTP_200_OK)