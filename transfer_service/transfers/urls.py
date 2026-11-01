from django.urls import path

from transfers.views import (
    TransferCreateAPIView,
    TransferDetailAPIView,
    TransferRecoveryAPIView,
)

urlpatterns = [
    path(
        "transfers/",
        TransferCreateAPIView.as_view(),
        name="create-transfer"
    ),

    path(
        "transfers/<uuid:transfer_id>/",
        TransferDetailAPIView.as_view(),
        name="transfer-detail"
    ),

    path(
    "transfers/<uuid:transfer_id>/recovery/",
    TransferRecoveryAPIView.as_view(),
    name="transfer-recovery"
),
]