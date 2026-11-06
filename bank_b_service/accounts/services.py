from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from accounts.models import BankAccount
from ledger.models import LedgerEntry


def create_account(
    account_number,
    customer_name,
    initial_balance=Decimal("0.00"),
    currency="RWF",
    owner_customer_id=None
):
    initial_balance = Decimal(str(initial_balance))

    if initial_balance < 0:
        raise ValidationError("Initial balance cannot be negative.")

    if initial_balance.as_tuple().exponent < -2:
        raise ValidationError(
            "Amount cannot have more than two decimal places."
        )

    if not account_number or not customer_name:
        raise ValidationError(
            "Account number and customer name are required."
        )

    return BankAccount.objects.create(
        account_number=account_number,
        customer_name=customer_name,
        balance=initial_balance,
        currency=currency,
        owner_customer_id=owner_customer_id
    )


def get_account_balance(account_id):
    account = get_object_or_404(
        BankAccount,
        id=account_id
    )

    return {
        "account_id": str(account.id),
        "account_number": account.account_number,
        "currency": account.currency,
        "balance": account.balance
    }


@transaction.atomic
def credit_account(account_id, transfer_id, amount):
    """
    Credit the receiver's account exactly once per transfer ID.

    Repeated requests with the same transfer ID and same details
    return the existing ledger entry without crediting again.
    """

    amount = Decimal(str(amount))
    transfer_id = UUID(str(transfer_id))

    if amount <= 0:
        raise ValidationError(
            "Credit amount must be greater than zero."
        )

    if amount.as_tuple().exponent < -2:
        raise ValidationError(
            "Amount cannot have more than two decimal places."
        )

    # Lock the receiver account to prevent concurrent balance updates.
    account = get_object_or_404(
        BankAccount.objects.select_for_update(),
        id=account_id
    )

    if account.status != BankAccount.AccountStatus.ACTIVE:
        raise ValidationError("Receiver account is not active.")

    # Check whether this transfer was already credited.
    existing_entry = LedgerEntry.objects.filter(
        transfer_id=transfer_id
    ).first()

    if existing_entry:
        if (
            existing_entry.account_id != account.id
            or existing_entry.amount != amount
        ):
            raise ValidationError(
                "Transfer ID already exists with different details."
            )

        return existing_entry

    if account.currency != "RWF":
        raise ValidationError("Unsupported account currency.")

    # Update the receiver's posted balance.
    account.balance += amount

    account.save(
        update_fields=["balance", "updated_at"]
    )

    # Record the credit in the ledger.
    ledger_entry = LedgerEntry.objects.create(
        account=account,
        transfer_id=transfer_id,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=amount,
        description="Interbank transfer received"
    )

    return ledger_entry

def get_transfer_status(transfer_id):
    """
    Retrieve the current credit status for a transfer.
    """

    transfer_id = UUID(str(transfer_id))

    ledger_entry = get_object_or_404(
        LedgerEntry.objects.select_related("account"),
        transfer_id=transfer_id
    )

    return {
        "transfer_id": str(transfer_id),
        "account_id": str(ledger_entry.account_id),
        "account_number": ledger_entry.account.account_number,
        "amount": str(ledger_entry.amount),
        "currency": ledger_entry.account.currency,
        "status": (
            "CREDITED"
            if ledger_entry.entry_type == LedgerEntry.EntryType.CREDIT
            else "INVALID_ENTRY"
        ),
    }