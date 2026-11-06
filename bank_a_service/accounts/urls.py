from django.urls import path

from accounts.views import (
    BankAccountListCreateAPIView,
    AccountBalanceAPIView,
    LinkAccountOwnershipAPIView,
    ReserveFundsAPIView,
    CommitReservationAPIView,
    ReleaseReservationAPIView,
    TransferStatusAPIView,
    VerifyAccountOwnershipAPIView,
    CustomerBankAccountsAPIView,
    CashDepositAPIView,
    MobileMoneyDepositAPIView,
    CashWithdrawalAPIView,
    CustomerAccountTransactionsAPIView
)


from ledger.views import LedgerEntriesAPIView

urlpatterns = [
    path('accounts/',BankAccountListCreateAPIView.as_view(),name='bank-account-list-create'),
    path('accounts/<uuid:account_id>/balance/',AccountBalanceAPIView.as_view(),name='account-balance'),
    path('transfers/reserve/',ReserveFundsAPIView.as_view(),name='reserve-funds'),
    path('transfers/commit/',CommitReservationAPIView.as_view(),name='commit-reservation'),
    path('transfers/release/',ReleaseReservationAPIView.as_view(),name='release-reservation'),
    path('transfers/<uuid:transfer_id>/status/',TransferStatusAPIView.as_view(),name='transfer-status'),
    path("accounts/link-owner/",LinkAccountOwnershipAPIView.as_view(),name="link-account-owner"),
    path("internal/accounts/verify-ownership/",VerifyAccountOwnershipAPIView.as_view(), name="verify-account-ownership"),
    path('accounts/customer/<uuid:customer_id>/',CustomerBankAccountsAPIView.as_view(),name='customer-bank-accounts'),
    path("ledger/entries/", LedgerEntriesAPIView.as_view(), name="ledger-entries"),
    path("accounts/deposits/cash/", CashDepositAPIView.as_view(), name="cash-deposit"),
    path("accounts/deposits/mobile-money/",MobileMoneyDepositAPIView.as_view(),name="mobile-money-deposit",),
    path("accounts/withdrawals/cash/",CashWithdrawalAPIView.as_view(),name="cash-withdrawal",),
    path("transactions/customer/<uuid:customer_id>/",CustomerAccountTransactionsAPIView.as_view(),name="customer-account-transactions"),
]