from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from sympy import Sum

from accounts.models import BankAccount
from ledger.models import AccountTransaction, LedgerEntry


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

def _validate_account_transaction_amount(amount):
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Amount must be a valid decimal number.")

    if not amount.is_finite() or amount <= Decimal("0"):
        raise ValidationError("Amount must be greater than zero.")

    if amount.as_tuple().exponent < -2:
        raise ValidationError("Amount cannot have more than two decimal places.")

    return amount


def _process_account_transaction(
    *,
    account_id,
    customer_id,
    transaction_reference,
    amount,
    transaction_type,
    description="",
):
    """
    Atomically update the account balance and create the transaction record.
    Repeating the same reference and payload returns the original transaction.
    """

    try:
        customer_id = UUID(str(customer_id))
        transaction_reference = UUID(str(transaction_reference))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Customer ID and transaction reference must be valid UUIDs.")

    amount = _validate_account_transaction_amount(amount)

    allowed_types = {
        AccountTransaction.TransactionType.CASH_DEPOSIT,
        AccountTransaction.TransactionType.MOBILE_MONEY_DEPOSIT,
        AccountTransaction.TransactionType.CASH_WITHDRAWAL,
    }
    if transaction_type not in allowed_types:
        raise ValidationError("Unsupported account transaction type.")

    with transaction.atomic():
        account = get_object_or_404(
            BankAccount.objects.select_for_update(),
            id=account_id,
        )

        if account.owner_customer_id != customer_id:
            raise ValidationError("Customer does not own this bank account.")

        if account.status != BankAccount.AccountStatus.ACTIVE:
            raise ValidationError("Bank account is not active.")

        existing = AccountTransaction.objects.filter(
            transaction_reference=transaction_reference
        ).first()

        if existing:
            if (
                existing.account_id != account.id
                or existing.customer_id != customer_id
                or existing.amount != amount
                or existing.transaction_type != transaction_type
            ):
                raise ValidationError(
                    "Transaction reference already exists with different details."
                )
            return existing, False

        balance_before = account.balance

        if transaction_type == AccountTransaction.TransactionType.CASH_WITHDRAWAL:
            reserved_total = (
                AccountReservation.objects.filter(
                    account=account,
                    status=AccountReservation.ReservationStatus.RESERVED,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            available_balance = account.balance - reserved_total

            if available_balance < amount:
                raise ValidationError("Insufficient available balance.")

            account.balance -= amount
        else:
            account.balance += amount

        account.save(update_fields=["balance", "updated_at"])

        account_transaction = AccountTransaction.objects.create(
            account=account,
            transaction_reference=transaction_reference,
            transaction_type=transaction_type,
            amount=amount,
            currency=account.currency,
            balance_before=balance_before,
            balance_after=account.balance,
            customer_id=customer_id,
            description=(description or "")[:255],
        )

        return account_transaction, True


def deposit_cash(
    *,
    account_id,
    customer_id,
    transaction_reference,
    amount,
    description="",
):
    return _process_account_transaction(
        account_id=account_id,
        customer_id=customer_id,
        transaction_reference=transaction_reference,
        amount=amount,
        transaction_type=AccountTransaction.TransactionType.CASH_DEPOSIT,
        description=description,
    )


def deposit_mobile_money(
    *,
    account_id,
    customer_id,
    transaction_reference,
    amount,
    description="",
):
    # Academic simulation: the caller represents a trusted, verified funding flow.
    return _process_account_transaction(
        account_id=account_id,
        customer_id=customer_id,
        transaction_reference=transaction_reference,
        amount=amount,
        transaction_type=AccountTransaction.TransactionType.MOBILE_MONEY_DEPOSIT,
        description=description,
    )


def withdraw_cash(
    *,
    account_id,
    customer_id,
    transaction_reference,
    amount,
    description="",
):
    return _process_account_transaction(
        account_id=account_id,
        customer_id=customer_id,
        transaction_reference=transaction_reference,
        amount=amount,
        transaction_type=AccountTransaction.TransactionType.CASH_WITHDRAWAL,
        description=description,
    )

