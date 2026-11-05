from django.template import response
import requests
from django.conf import settings


class BankBClient:

    def __init__(self):
        self.base_url = settings.BANK_B_BASE_URL
        self.timeout = settings.BANK_REQUEST_TIMEOUT

        self.headers = {
            "X-Service-Token": settings.BANK_B_INTERNAL_SERVICE_TOKEN
        }

    def credit_account(self, account_id, transfer_id, amount):
        url = f"{self.base_url}/api/transfers/credit/"

        response = requests.post(
            url,
            json={
                "account_id": str(account_id),
                "transfer_id": str(transfer_id),
                "amount": str(amount),
            },
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
        url = f"{self.base_url.rstrip('/')}/api/accounts/"

        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()


    def lookup_account(self, account_number):
        url = (
            f"{self.base_url.rstrip('/')}/api/accounts/lookup/"
        )

        response = requests.get(
            url,
            params={"account_number": account_number},
            headers=self.headers,
            timeout=self.timeout
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()