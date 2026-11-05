from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transfers.models import Transfer
from transfers.permissions import IsSystemAdmin


RECOVERY_STATUSES = [
    Transfer.TransferStatus.REQUIRES_REVIEW,
    Transfer.TransferStatus.RECOVERING,
    Transfer.TransferStatus.RESERVED,
    Transfer.TransferStatus.CREDITING,
    Transfer.TransferStatus.CREDITED,
    Transfer.TransferStatus.COMMITTING,
    Transfer.TransferStatus.RESERVING,
]


class RecoveryMonitoringPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class RecoveryMonitoringAPIView(APIView):
    """
    System-administrator-only list and summary for recovery monitoring.
    Does not contact Bank A or Bank B; use the existing per-transfer
    recovery inspection endpoint for reconciliation details.
    """
    permission_classes = [IsAuthenticated, IsSystemAdmin]

    def get(self, request):
        all_transfers = Transfer.objects.all()
        now = timezone.now()

        summary = {
            "requires_review": all_transfers.filter(
                status=Transfer.TransferStatus.REQUIRES_REVIEW
            ).count(),
            "recovering": all_transfers.filter(
                status=Transfer.TransferStatus.RECOVERING
            ).count(),
            "dead_lettered": all_transfers.filter(
                dead_lettered_at__isnull=False
            ).count(),
            "awaiting_retry": all_transfers.filter(
                status__in=RECOVERY_STATUSES,
                dead_lettered_at__isnull=True,
                recovery_deadline__isnull=False,
            ).filter(
                recovery_deadline__gt=now,
            ).filter(
                Q(next_retry_at__isnull=True)
                | Q(next_retry_at__lte=now)
            ).count(),
        }

        queryset = all_transfers.exclude(
            status__in=[
                Transfer.TransferStatus.COMPLETED,
                Transfer.TransferStatus.FAILED,
                Transfer.TransferStatus.PENDING,
            ]
        )

        search = request.query_params.get("search", "").strip()
        if search:
            filters = (
                Q(source_account_number__icontains=search)
                | Q(destination_account_number__icontains=search)
                | Q(current_step__icontains=search)
            )
            try:
                import uuid
                filters |= Q(id=uuid.UUID(search))
            except ValueError:
                pass
            queryset = queryset.filter(filters)

        status_filter = request.query_params.get("status", "").strip()
        if status_filter:
            valid_statuses = [value for value, _ in Transfer.TransferStatus.choices]
            if status_filter not in valid_statuses:
                return Response(
                    {"message": "Invalid transfer status."},
                    status=400,
                )
            queryset = queryset.filter(status=status_filter)

        bucket = request.query_params.get("bucket", "").strip()
        if bucket == "dead_lettered":
            queryset = queryset.filter(dead_lettered_at__isnull=False)
        elif bucket == "requires_review":
            queryset = queryset.filter(
                status=Transfer.TransferStatus.REQUIRES_REVIEW
            )
        elif bucket == "recovering":
            queryset = queryset.filter(
                status=Transfer.TransferStatus.RECOVERING
            )
        elif bucket == "awaiting_retry":
            queryset = queryset.filter(
                status__in=RECOVERY_STATUSES,
                dead_lettered_at__isnull=True,
                recovery_deadline__gt=now,
            ).filter(
                Q(next_retry_at__isnull=True)
                | Q(next_retry_at__lte=now)
            )
        elif bucket and bucket != "all":
            return Response({"message": "Invalid recovery bucket."}, status=400)

        queryset = queryset.order_by("-updated_at", "-created_at")

        paginator = RecoveryMonitoringPagination()
        page = paginator.paginate_queryset(queryset, request)

        rows = [{
            "id": str(item.id),
            "source_account_number": item.source_account_number,
            "destination_account_number": item.destination_account_number,
            "amount": str(item.amount),
            "currency": item.currency,
            "status": item.status,
            "current_step": item.current_step,
            "retry_count": item.retry_count,
            "max_retries": item.max_retries,
            "next_retry_at": item.next_retry_at,
            "recovery_started_at": item.recovery_started_at,
            "recovery_lease_until": item.recovery_lease_until,
            "recovery_deadline": item.recovery_deadline,
            "dead_lettered_at": item.dead_lettered_at,
            "last_error_at": item.last_error_at,
            "failure_reason": item.failure_reason,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        } for item in page]

        response = paginator.get_paginated_response({
            "summary": summary,
            "transfers": rows,
        })
        return response


class RecoveryMonitoringDetailAPIView(APIView):
    """
    Administrator detail endpoint. Returns coordinator data and Saga steps
    even when a bank service is unavailable; bank reconciliation is optional
    and its error is reported separately.
    """
    permission_classes = [IsAuthenticated, IsSystemAdmin]

    def get(self, request, transfer_id):
        try:
            transfer = Transfer.objects.get(id=transfer_id)
        except Transfer.DoesNotExist:
            return Response({"message": "Transfer not found."}, status=404)

        from transfers.services.recovery_service import TransferRecoveryService

        inspection = None
        inspection_error = None
        try:
            inspection = TransferRecoveryService().inspect_transfer(transfer.id)
        except Exception as exc:
            inspection_error = str(exc)

        steps = list(transfer.steps.values(
            "step_name",
            "status",
            "attempt_count",
            "error_message",
            "started_at",
            "completed_at",
        ))

        return Response({
            "transfer": {
                "id": str(transfer.id),
                "source_account_number": transfer.source_account_number,
                "destination_account_number": transfer.destination_account_number,
                "amount": str(transfer.amount),
                "currency": transfer.currency,
                "status": transfer.status,
                "current_step": transfer.current_step,
                "retry_count": transfer.retry_count,
                "max_retries": transfer.max_retries,
                "next_retry_at": transfer.next_retry_at,
                "recovery_started_at": transfer.recovery_started_at,
                "recovery_lease_until": transfer.recovery_lease_until,
                "recovery_deadline": transfer.recovery_deadline,
                "dead_lettered_at": transfer.dead_lettered_at,
                "failure_reason": transfer.failure_reason,
                "created_at": transfer.created_at,
                "completed_at": transfer.completed_at,
            },
            "recovery_inspection": inspection,
            "bank_inspection_error": inspection_error,
            "execution_history": steps,
        }, status=200)


@login_required(login_url="login")
def recovery_monitoring_page(request):
    try:
        role = request.user.profile.role
    except Exception:
        raise PermissionDenied("A configured user profile is required.")

    if role != "SYSTEM_ADMIN":
        raise PermissionDenied("System administrator access is required.")

    return render(request, "transfers/recovery_monitoring.html")
