from django.utils.dateparse import parse_date
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LedgerEntry
from accounts.permissions import IsInternalService


class LedgerEntryPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500


class LedgerEntriesAPIView(APIView):

    authentication_classes = []
    permission_classes = [IsInternalService]

    def get(self, request):
        queryset = LedgerEntry.objects.select_related("account").all()

        transfer_id = request.query_params.get("transfer_id")
        account_number = request.query_params.get("account_number")
        entry_type = request.query_params.get("entry_type")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if transfer_id:
            queryset = queryset.filter(transfer_id=transfer_id)

        if account_number:
            queryset = queryset.filter(
                account__account_number__icontains=account_number
            )

        if entry_type:
            queryset = queryset.filter(entry_type=entry_type.upper())

        if start_date:
            parsed_date = parse_date(start_date)
            if not parsed_date:
                return Response(
                    {"message": "Invalid start_date. Use YYYY-MM-DD."},
                    status=400
                )
            queryset = queryset.filter(created_at__date__gte=parsed_date)

        if end_date:
            parsed_date = parse_date(end_date)
            if not parsed_date:
                return Response(
                    {"message": "Invalid end_date. Use YYYY-MM-DD."},
                    status=400
                )
            queryset = queryset.filter(created_at__date__lte=parsed_date)

        paginator = LedgerEntryPagination()

        page = paginator.paginate_queryset(
            queryset.order_by("-created_at"),
            request,
            view=self
        )

        records = []

        for entry in page:
            records.append({
                "id": str(entry.id),
                "transfer_id": str(entry.transfer_id),
                "entry_type": entry.entry_type,
                "amount": str(entry.amount),
                "currency": entry.account.currency,
                "account_id": str(entry.account_id),
                "account_number": entry.account.account_number,
                "description": entry.description,
                "created_at": entry.created_at.isoformat(),
            })

        return paginator.get_paginated_response(records)
