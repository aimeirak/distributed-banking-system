from django.urls import path

from accounts.views import (
    BankAccountListCreateAPIView,
    AccountBalanceAPIView,
    ReserveFundsAPIView,
    CommitReservationAPIView,
    ReleaseReservationAPIView
)

urlpatterns = [
    path('accounts/',BankAccountListCreateAPIView.as_view(),name='bank-account-list-create'),
    path('accounts/<uuid:account_id>/balance/',AccountBalanceAPIView.as_view(),name='account-balance'),
    path('transfers/reserve/',ReserveFundsAPIView.as_view(),name='reserve-funds'),
    path('transfers/commit/',CommitReservationAPIView.as_view(),name='commit-reservation'),
    path('transfers/release/',ReleaseReservationAPIView.as_view(),name='release-reservation'),
]