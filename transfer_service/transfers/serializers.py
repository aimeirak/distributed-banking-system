from decimal import Decimal

from rest_framework import serializers

from transfers.models import Transfer

from django.contrib.auth.models import User
from rest_framework import serializers
from transfers.models import UserProfile


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

class CustomerRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8
    )

    phone_number = serializers.CharField(
        required=False,
        allow_blank=True
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "phone_number",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        phone_number = validated_data.pop("phone_number", "")

        user = User.objects.create_user(**validated_data)

        UserProfile.objects.create(
            user=user,
            role=UserProfile.Role.CUSTOMER,
            phone_number=phone_number
        )

        return user  