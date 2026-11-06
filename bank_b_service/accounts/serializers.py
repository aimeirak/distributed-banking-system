from rest_framework import serializers
from accounts.models import BankAccount
from ledger.models import AccountTransaction


class BankAccountSerializer(serializers.ModelSerializer):

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "account_number",
            "customer_name",
            "currency",
            "balance",
            "status",
            "owner_customer_id",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "owner_customer_id",
            "created_at",
        ]


class CreditAccountSerializer(serializers.Serializer):

    account_id = serializers.UUIDField()

    transfer_id = serializers.UUIDField()

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0.01
    )

class AccountTransactionRequestSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    transaction_reference = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0.01,
    )
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )

class AccountTransactionResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    transaction_reference = serializers.UUIDField()
    transaction_type = serializers.CharField()
    account_id = serializers.UUIDField()
    account_number = serializers.CharField()
    customer_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    balance_before = serializers.DecimalField(max_digits=18, decimal_places=2)
    balance_after = serializers.DecimalField(max_digits=18, decimal_places=2)
    description = serializers.CharField()
    created_at = serializers.DateTimeField()

class AccountTransactionHistorySerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(
        source="account.account_number",
        read_only=True
    )
    class Meta:
        model = AccountTransaction
        fields = [
            "id",
            "transaction_reference",
            "account_number",
            "transaction_type",
            "amount",
            "currency",
            "balance_before",
            "balance_after",
            "description",
            "created_at",
        ]