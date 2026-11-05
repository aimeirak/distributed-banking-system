from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from transfers.views import (
    TransferCreateAPIView,
    TransferDetailAPIView,
    TransferRecoveryAPIView,
    CustomerRegistrationAPIView,
    CustomerProfileAPIView,
    CustomerSourceAccountsAPIView,
    VerifyDestinationAccountAPIView,
)

from transfers import views
from transfers.auth_views import login_page, logout_page


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

    path("transfers/create/", views.new_transfer_page, name="new-transfer-page"),

    path("login/", login_page, name="login"),

    path("logout/", logout_page, name="logout"),
]