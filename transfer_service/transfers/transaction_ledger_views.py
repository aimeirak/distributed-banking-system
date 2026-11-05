from datetime import datetime, time
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .permissions import IsSystemAdmin
from .services.bank_a_client import BankAClient
from .services.bank_b_client import BankBClient


def _results(payload):
    """Accept DRF pagination or a plain list without assuming one response shape."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            return payload["results"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
        if isinstance(payload.get("data"), dict):
            data = payload["data"]
            if isinstance(data.get("results"), list):
                return data["results"]
    return []


def _normalize(records, bank):
    normalized = []
    for item in records:
        row = dict(item)
        row["bank"] = bank
        row["id"] = str(row.get("id", ""))
        row["transfer_id"] = str(row.get("transfer_id", ""))
        row["amount"] = str(row.get("amount", "0.00"))
        normalized.append(row)
    return normalized


@login_required(login_url="login")
def transaction_ledger_page(request):
    try:
        if request.user.profile.role != "SYSTEM_ADMIN":
            return HttpResponseForbidden("You do not have permission to access the transaction ledger.")
    except Exception:
        return HttpResponseForbidden("You do not have permission to access the transaction ledger.")
    return render(request, "transfers/transaction_ledger.html")


class TransactionLedgerAPIView(APIView):
    permission_classes = [IsAuthenticated, IsSystemAdmin]

    def get(self, request):
        bank_filter = request.query_params.get("bank", "ALL").upper()
        entry_type = request.query_params.get("entry_type", "").upper()
        transfer_id = request.query_params.get("transfer_id", "").strip()
        account_number = request.query_params.get("account_number", "").strip()
        start_date = request.query_params.get("start_date", "")
        end_date = request.query_params.get("end_date", "")

        bank_params = {}
        if transfer_id:
            bank_params["transfer_id"] = transfer_id
        if account_number:
            bank_params["account_number"] = account_number
        if entry_type:
            bank_params["entry_type"] = entry_type
        if start_date:
            bank_params["start_date"] = start_date
        if end_date:
            bank_params["end_date"] = end_date
        # Each bank endpoint caps page_size at 500. Fetch the first 500 from
        # each bank, merge globally, then paginate once at the coordinator.
        bank_params["page_size"] = 500

        rows, errors = [], []
        if bank_filter in ("ALL", "BANK_A"):
            try:
                rows.extend(_normalize(_results(BankAClient().get_ledger_entries(bank_params)), "BANK_A"))
            except Exception as exc:
                errors.append({"bank": "BANK_A", "message": str(exc)})
        if bank_filter in ("ALL", "BANK_B"):
            try:
                rows.extend(_normalize(_results(BankBClient().get_ledger_entries(bank_params)), "BANK_B"))
            except Exception as exc:
                errors.append({"bank": "BANK_B", "message": str(exc)})

        # Global filter after merge (also protects against inconsistent bank filters).
        if entry_type:
            rows = [r for r in rows if str(r.get("entry_type", "")).upper() == entry_type]
        if transfer_id:
            rows = [r for r in rows if r.get("transfer_id") == transfer_id]
        if account_number:
            rows = [r for r in rows if account_number.lower() in str(r.get("account_number", "")).lower()]

        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)

        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        try:
            page_number = max(int(request.query_params.get("page", 1)), 1)
        except ValueError:
            page_number = 1
        total = len(rows)
        start = (page_number - 1) * page_size
        page_rows = rows[start:start + page_size]

        totals = {"RESERVATION": Decimal("0"), "DEBIT": Decimal("0"),
                  "RELEASE": Decimal("0"), "CREDIT": Decimal("0")}
        for row in rows:
            kind = str(row.get("entry_type", "")).upper()
            if kind in totals:
                try:
                    totals[kind] += Decimal(str(row.get("amount", "0")))
                except Exception:
                    pass

        return Response({
            "count": total,
            "page": page_number,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "results": page_rows,
            "summary": {key: str(value) for key, value in totals.items()},
            "source_errors": errors,
            "partial": bool(errors),
            "retrieval_limit_per_bank": 500,
        }, status=status.HTTP_200_OK)
