from django.urls import path

from accounts.views import (
    BankAccountListCreateAPIView,
    AccountBalanceAPIView,
    LinkAccountOwnershipAPIView,
    ReserveFundsAPIView,
    CommitReservationAPIView,
    ReleaseReservationAPIView,
    TransferStatusAPIView,
    VerifyAccountOwnershipAPIView
)

urlpatterns = [
    path('accounts/',BankAccountListCreateAPIView.as_view(),name='bank-account-list-create'),
    path('accounts/<uuid:account_id>/balance/',AccountBalanceAPIView.as_view(),name='account-balance'),
    path('transfers/reserve/',ReserveFundsAPIView.as_view(),name='reserve-funds'),
    path('transfers/commit/',CommitReservationAPIView.as_view(),name='commit-reservation'),
    path('transfers/release/',ReleaseReservationAPIView.as_view(),name='release-reservation'),
    path('transfers/<uuid:transfer_id>/status/',TransferStatusAPIView.as_view(),name='transfer-status'),
    path("accounts/link-owner/",LinkAccountOwnershipAPIView.as_view(),name="link-account-owner"),
    path("internal/accounts/verify-ownership/",VerifyAccountOwnershipAPIView.as_view(), name="verify-account-ownership"),
]