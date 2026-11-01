from decimal import Decimal

from rest_framework import serializers

from transfers.models import Transfer


class TransferCreateSerializer(serializers.ModelSerializer):

    idempotency_key = serializers.UUIDField(
        required=True,
        write_only=True
    )

    class Meta:
        model = Transfer
        fields = [
            "id",
            "idempotency_key",
            "source_account_id",
            "destination_account_id",
            "source_account_number",
            "destination_account_number",
            "amount",
            "currency",
            "status",
            "created_at",
        ]

        read_only_fields = [
            "id",
            "status",
            "created_at",
        ]

    def validate_amount(self, value):
        if value <= Decimal("0.00"):
            raise serializers.ValidationError(
                "Transfer amount must be greater than zero."
            )
        return value

    def validate(self, attrs):

        if attrs["source_account_id"] == attrs["destination_account_id"]:
            raise serializers.ValidationError(
                "Source and destination accounts cannot be the same."
            )

        if attrs.get("currency", "RWF") != "RWF":
            raise serializers.ValidationError(
                "Only RWF transfers are supported."
            )

        return attrs