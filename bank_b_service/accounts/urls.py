from django.urls import path

from accounts.views import (
    BankAccountListCreateAPIView,
    AccountBalanceAPIView,
    CashDepositAPIView,
    CashWithdrawalAPIView,
    CreditAccountAPIView,
    CustomerAccountTransactionsAPIView,
    MobileMoneyDepositAPIView,
    TransferStatusAPIView,
    BankAccountLookupAPIView,
    CustomerBankAccountsAPIView
)
from ledger.views import LedgerEntriesAPIView

urlpatterns = [
    path('accounts/',BankAccountListCreateAPIView.as_view(),name='bank-account-list-create'),
    path('accounts/<uuid:account_id>/balance/',AccountBalanceAPIView.as_view(),name='account-balance'),
    path('transfers/credit/',CreditAccountAPIView.as_view(),name='credit-account'),
    path('transfers/<uuid:transfer_id>/status/',TransferStatusAPIView.as_view(),name='transfer-status'),
    path('accounts/lookup/',BankAccountLookupAPIView.as_view(),name='bank-account-lookup'),
    path("ledger/entries/",LedgerEntriesAPIView.as_view(),name="ledger-entries"),
    path('accounts/customer/<uuid:customer_id>/',CustomerBankAccountsAPIView.as_view(), name='customer-bank-accounts'),
    path("accounts/deposits/cash/", CashDepositAPIView.as_view(), name="cash-deposit"),
    path("accounts/deposits/mobile-money/",MobileMoneyDepositAPIView.as_view(),name="mobile-money-deposit",),
    path("accounts/withdrawals/cash/",CashWithdrawalAPIView.as_view(),name="cash-withdrawal",),
    path("transactions/customer/<uuid:customer_id>/",CustomerAccountTransactionsAPIView.as_view(),name="customer-account-transactions"),
]
