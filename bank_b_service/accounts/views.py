from django.shortcuts import render
# Create your views here.
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from accounts.models import BankAccount
from accounts.serializers import (
    BankAccountSerializer,
    CreditAccountSerializer
)

from accounts.services import (
    create_account,
    get_account_balance,
    credit_account,
    get_transfer_status
)

from accounts.permissions import (
    IsInternalService,
    IsAccountAdministrator
)


class BankAccountListCreateAPIView(APIView):

    permission_classes = [IsAccountAdministrator]

    def get(self, request):
        accounts = BankAccount.objects.all()

        serializer = BankAccountSerializer(
            accounts,
            many=True
        )

        return Response(serializer.data)

    def post(self, request):
        serializer = BankAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            account = create_account(
                account_number=serializer.validated_data['account_number'],
                customer_name=serializer.validated_data['customer_name'],
                initial_balance=serializer.validated_data.get(
                    'balance', 0
                ),
                currency=serializer.validated_data.get(
                    'currency', 'RWF'
                )
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

        except Http404:
            return Response(
                {'error': 'Bank account not found.'},
                status=status.HTTP_404_NOT_FOUND
            )


class CreditAccountAPIView(APIView):

    permission_classes = [IsInternalService]

    def post(self, request):
        serializer = CreditAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ledger_entry = credit_account(
                account_id=serializer.validated_data['account_id'],
                transfer_id=serializer.validated_data['transfer_id'],
                amount=serializer.validated_data['amount']
            )

            return Response(
                {
                    'message': 'Account credited successfully.',
                    'transfer_id': str(ledger_entry.transfer_id),
                    'account_id': str(ledger_entry.account_id),
                    'amount': str(ledger_entry.amount),
                    'status': 'CREDITED'
                },
                status=status.HTTP_200_OK
            )

        except DjangoValidationError as exc:
            return Response(
                {'error': exc.messages},
                status=status.HTTP_400_BAD_REQUEST
            )

        except Http404:
            return Response(
                {'error': 'Receiver account not found.'},
                status=status.HTTP_404_NOT_FOUND
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
                        "message": "Transfer credit not found.",
                        "transfer_id": str(transfer_id)
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

            raise

class BankAccountLookupAPIView(APIView):
    permission_classes = [IsInternalService]

    def get(self, request):
        account_number = request.query_params.get("account_number")

        if not account_number:
            return Response(
                {"message": "Account number is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            account = BankAccount.objects.get(
                account_number=account_number.strip()
            )

        except BankAccount.DoesNotExist:
            return Response(
                {"message": "Bank account not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if account.status != BankAccount.AccountStatus.ACTIVE:
            return Response(
                {"message": "Receiver account is not active."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "verified": True,
            "account_id": str(account.id),
            "account_number": account.account_number,
            "customer_name": account.customer_name,
            "currency": account.currency,
            "status": account.status
        }, status=status.HTTP_200_OK)