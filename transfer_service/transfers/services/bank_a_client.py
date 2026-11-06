from urllib import response

import requests
from django.conf import settings


class BankAClient:

    def __init__(self):
        self.base_url = settings.BANK_A_BASE_URL.rstrip("/")
        self.timeout = settings.BANK_REQUEST_TIMEOUT
        self.headers = {
            "X-Service-Token": settings.BANK_A_INTERNAL_SERVICE_TOKEN
        }

    def verify_account_ownership(self, account_id, customer_id):
        url = f"{self.base_url}/api/internal/accounts/verify-ownership/"

        response = requests.post(
            url,
            json={
                "account_id": str(account_id),
                "customer_id": str(customer_id)
            },
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def reserve_funds(self, account_id, transfer_id, amount):
        url = f"{self.base_url}/api/transfers/reserve/"

        response = requests.post(
            url,
            json={
                "account_id": str(account_id),
                "transfer_id": str(transfer_id),
                "amount": str(amount)
            },
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def commit_reservation(self, transfer_id):
        url = f"{self.base_url}/api/transfers/commit/"

        response = requests.post(
            url,
            json={"transfer_id": str(transfer_id)},
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def release_reservation(self, transfer_id):
        url = f"{self.base_url}/api/transfers/release/"

        response = requests.post(
            url,
            json={"transfer_id": str(transfer_id)},
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def get_transfer_status(self, transfer_id):
        url = f"{self.base_url}/api/transfers/{transfer_id}/status/"

        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()["data"]

    def get_accounts(self):
        url = f"{self.base_url}/api/accounts/"

        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def get_customer_accounts(self, customer_id):
        url = (
            f"{self.base_url}/api/accounts/customer/"
            f"{customer_id}/"
        )

        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def get_ledger_entries(self, params=None):
        url = f"{self.base_url.rstrip('/')}/api/ledger/entries/"

        response = requests.get(
            url,
            params=params or {},
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()

        return response.json()

    def create_account(
        self,
        account_number,
        customer_name,
        customer_id,
        currency="RWF",
        initial_balance="0.00"
    ):
        url = f"{self.base_url}/api/accounts/"

        response = requests.post(
            url,
            json={
                "account_number": account_number,
                "customer_name": customer_name,
                "currency": currency,
                "balance": initial_balance,
                "owner_customer_id": str(customer_id),
            },
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def create_account_transaction(
        self, transaction_type, account_id, customer_id,
        transaction_reference, amount, description=""
    ):
        endpoint_by_type = {
            "CASH_DEPOSIT": "deposits/cash/",
            "MOBILE_MONEY_DEPOSIT": "deposits/mobile-money/",
            "CASH_WITHDRAWAL": "withdrawals/cash/",
        }
        if transaction_type not in endpoint_by_type:
            raise ValueError("Unsupported account transaction type.")

        url = (
            f"{self.base_url.rstrip('/')}/api/accounts/"
            f"{endpoint_by_type[transaction_type]}"
        )
        response = requests.post(
            url,
            json={
                "account_id": str(account_id),
                "customer_id": str(customer_id),
                "transaction_reference": str(transaction_reference),
                "amount": str(amount),
                "description": description,
            },
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


    def get_customer_transactions(self, customer_id):
        url = (
            f"{self.base_url.rstrip('/')}/api/accounts/"
            f"transactions/customer/{customer_id}/"
        )

        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()