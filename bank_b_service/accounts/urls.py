from django.urls import path

from accounts.views import (
    BankAccountListCreateAPIView,
    AccountBalanceAPIView,
    CreditAccountAPIView,
    TransferStatusAPIView
)

urlpatterns = [
    path(
        'accounts/',
        BankAccountListCreateAPIView.as_view(),
        name='bank-account-list-create'
    ),

    path(
        'accounts/<uuid:account_id>/balance/',
        AccountBalanceAPIView.as_view(),
        name='account-balance'
    ),

    path(
        'transfers/credit/',
        CreditAccountAPIView.as_view(),
        name='credit-account'
    ),

    path(
    'transfers/<uuid:transfer_id>/status/',
    TransferStatusAPIView.as_view(),
    name='transfer-status'
),
]