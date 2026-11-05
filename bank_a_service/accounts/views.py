from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from accounts.serializers import LinkAccountOwnershipSerializer
from accounts.services import link_account_to_customer
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
                initial_balance=serializer.validated_data.get(
                    'balance', 0
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