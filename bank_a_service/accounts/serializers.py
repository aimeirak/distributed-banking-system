from rest_framework import serializers
from accounts.models import BankAccount


class BankAccountSerializer(serializers.ModelSerializer):

    class Meta:
        model = BankAccount
        fields = [
            'id',
            'account_number',
            'customer_name',
            'currency',
            'balance',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ReserveFundsSerializer(serializers.Serializer):

    account_id = serializers.UUIDField()
    transfer_id = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0.01
    )


class TransferActionSerializer(serializers.Serializer):

    transfer_id = serializers.UUIDField()