from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from transfers.views import (
    CustomerBankingTransactionsAPIView,
    TransferCreateAPIView,
    TransferDetailAPIView,
    TransferRecoveryAPIView,
    CustomerRegistrationAPIView,
    CustomerProfileAPIView,
    CustomerSourceAccountsAPIView,
    VerifyDestinationAccountAPIView,
    CustomerTransferListAPIView,
    AccountManagementAPIView,
    AdminAccountManagementAPIView,
    BanksPageView,
    CustomerBankingAPIView,
    MyBankingPageView
)
from transfers.recovery_views import (
    RecoveryMonitoringAPIView,
    RecoveryMonitoringDetailAPIView,
    recovery_monitoring_page,

)
from transfers.transaction_ledger_views import (
    TransactionLedgerAPIView,
    transaction_ledger_page,
)
from transfers import views
from transfers.auth_views import login_page, logout_page,register_page
urlpatterns = [
    path("auth/register/", CustomerRegistrationAPIView.as_view(), name="customer-register"),
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/profile/", CustomerProfileAPIView.as_view(), name="customer-profile"),
    path("transfers/", TransferCreateAPIView.as_view(), name="create-transfer"),
    path("transfers/<uuid:transfer_id>/", TransferDetailAPIView.as_view(), name="transfer-detail"),
    path("transfers/<uuid:transfer_id>/recovery/", TransferRecoveryAPIView.as_view(), name="transfer-recovery"),
    path("", views.dashboard, name="dashboard"),
    path("accounts/source/", CustomerSourceAccountsAPIView.as_view(), name="customer-source-accounts"),
    path("accounts/destination/verify/", VerifyDestinationAccountAPIView.as_view(), name="verify-destination-account"),
    path("accounts/",views.AccountManagementAPIView.as_view(), name="account-management-page"),
    path("transfers/create/", views.new_transfer_page, name="new-transfer-page"),
    path("login/", login_page, name="login"),
    path("logout/", logout_page, name="logout"),
    path("transfers/history/",CustomerTransferListAPIView.as_view(),name="customer-transfer-history"),
    path("transfers/history/page/",views.all_transfers_page,name="all-transfers-page"),
    path("recovery-monitoring/", recovery_monitoring_page,name="recovery-monitoring-page"),
    path("recovery/monitoring/api/",RecoveryMonitoringAPIView.as_view(),name="recovery-monitoring-api"),
    path("recovery/monitoring/api/<uuid:transfer_id>/",RecoveryMonitoringDetailAPIView.as_view(),name="recovery-monitoring-detail-api"),
    path("transactions/", transaction_ledger_page, name="transaction-ledger-page"),
    path("transactions/api/", TransactionLedgerAPIView.as_view(), name="transaction-ledger-api"),
    path("register/", register_page, name="register"),
    path("customers/",views.CustomerManagementView.as_view(),name="customer-management"),
    path( "customers/<int:pk>/",views.CustomerDetailView.as_view(),name="customer-detail"),
    path("api/admin/accounts/",views.AdminAccountManagementAPIView.as_view(),name="admin-account-management-api"),
    path("banks/", views.BanksPageView.as_view(), name="banks-page"),
    path("customer/banking/api/",CustomerBankingAPIView.as_view(),name="customer-banking-api"),
    path("my-banking/",views.MyBankingPageView.as_view(),name="my-banking-page"),
    path("customer/banking/transactions/",CustomerBankingTransactionsAPIView.as_view(),name="customer-banking-transactions-api"),
]