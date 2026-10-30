
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404

from accounts.models import BankAccount, AccountReservation
from ledger.models import LedgerEntry


def create_account(account_number, customer_name, initial_balance=Decimal("0.00"),
                   currency="RWF"):
    """
    Create a new bank account.

    Initial balance is supported for demo/test account setup.
    In production, opening funds should be recorded through a
    controlled funding operation and corresponding ledger entry.
    """

    initial_balance = Decimal(str(initial_balance))

    if initial_balance < 0:
        raise ValidationError("Initial balance cannot be negative.")

    if initial_balance.as_tuple().exponent < -2:
        raise ValidationError("Amount cannot have more than two decimal places.")

    if not account_number or not customer_name:
        raise ValidationError("Account number and customer name are required.")

    return BankAccount.objects.create(
        account_number=account_number,
        customer_name=customer_name,
        balance=initial_balance,
        currency=currency
    )


def get_account_balance(account_id):
    """
    Return posted balance, reserved amount and available balance.
    """

    account = get_object_or_404(BankAccount, id=account_id)

    reserved_amount = (
        AccountReservation.objects.filter(
            account=account,
            status=AccountReservation.ReservationStatus.RESERVED
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    return {
        "account_id": str(account.id),
        "account_number": account.account_number,
        "currency": account.currency,
        "posted_balance": account.balance,
        "reserved_amount": reserved_amount,
        "available_balance": account.balance - reserved_amount
    }


@transaction.atomic
def reserve_funds(account_id, transfer_id, amount):
    """
    Reserve funds for an interbank transfer.

    The posted balance is not changed at this stage.
    """

    amount = Decimal(str(amount))
    transfer_id = UUID(str(transfer_id))

    if amount <= 0:
        raise ValidationError("Transfer amount must be greater than zero.")

    if amount.as_tuple().exponent < -2:
        raise ValidationError("Amount cannot have more than two decimal places.")

    account = get_object_or_404(
        BankAccount.objects.select_for_update(),
        id=account_id
    )

    # Check for an existing reservation after acquiring the account lock.
    existing = AccountReservation.objects.filter(
        transfer_id=transfer_id
    ).first()

    if existing:
        if existing.account_id != account.id or existing.amount != amount:
            raise ValidationError(
                "Transfer reference already exists with different details."
            )

        if existing.status != AccountReservation.ReservationStatus.RESERVED:
            raise ValidationError(
                f"Reservation is already {existing.status}."
            )

        return existing

    if account.status != BankAccount.AccountStatus.ACTIVE:
        raise ValidationError("Bank account is not active.")

    reserved_amount = (
        AccountReservation.objects.filter(
            account=account,
            status=AccountReservation.ReservationStatus.RESERVED
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    available_balance = account.balance - reserved_amount

    if available_balance < amount:
        raise ValidationError("Insufficient available balance.")

    reservation = AccountReservation.objects.create(
        account=account,
        transfer_id=transfer_id,
        amount=amount,
        status=AccountReservation.ReservationStatus.RESERVED
    )

    LedgerEntry.objects.create(
        account=account,
        transfer_id=transfer_id,
        entry_type=LedgerEntry.EntryType.RESERVATION,
        amount=amount,
        description="Funds reserved for interbank transfer"
    )

    return reservation


@transaction.atomic
def commit_reservation(transfer_id):
    """
    Permanently debit the sender after the receiver bank
    has confirmed that the credit was successfully applied.
    """

    transfer_id = UUID(str(transfer_id))

    reservation_info = get_object_or_404(
        AccountReservation,
        transfer_id=transfer_id
    )

    # Always acquire locks in account-then-reservation order.
    account = get_object_or_404(
        BankAccount.objects.select_for_update(),
        id=reservation_info.account_id
    )

    reservation = get_object_or_404(
        AccountReservation.objects.select_for_update(),
        transfer_id=transfer_id
    )

    if reservation.status == AccountReservation.ReservationStatus.COMMITTED:
        return reservation

    if reservation.status != AccountReservation.ReservationStatus.RESERVED:
        raise ValidationError("Only active reservations can be committed.")

    if account.balance < reservation.amount:
        raise ValidationError("Insufficient posted balance.")

    account.balance -= reservation.amount
    account.save(update_fields=["balance", "updated_at"])

    LedgerEntry.objects.create(
        account=account,
        transfer_id=transfer_id,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=reservation.amount,
        description="Interbank transfer debit"
    )

    reservation.status = AccountReservation.ReservationStatus.COMMITTED
    reservation.save(update_fields=["status", "updated_at"])

    return reservation


@transaction.atomic
def release_reservation(transfer_id):
    """
    Release reserved funds when the transfer is safely compensated.
    The posted balance does not need to be increased because
    the funds were never debited.
    """

    transfer_id = UUID(str(transfer_id))

    reservation_info = get_object_or_404(
        AccountReservation,
        transfer_id=transfer_id
    )

    account = get_object_or_404(
        BankAccount.objects.select_for_update(),
        id=reservation_info.account_id
    )

    reservation = get_object_or_404(
        AccountReservation.objects.select_for_update(),
        transfer_id=transfer_id
    )

    if reservation.status == AccountReservation.ReservationStatus.RELEASED:
        return reservation

    if reservation.status != AccountReservation.ReservationStatus.RESERVED:
        raise ValidationError("Only active reservations can be released.")

    LedgerEntry.objects.create(
        account=account,
        transfer_id=transfer_id,
        entry_type=LedgerEntry.EntryType.RELEASE,
        amount=reservation.amount,
        description="Interbank transfer reservation released"
    )

    reservation.status = AccountReservation.ReservationStatus.RELEASED
    reservation.save(update_fields=["status", "updated_at"])

    return reservation
