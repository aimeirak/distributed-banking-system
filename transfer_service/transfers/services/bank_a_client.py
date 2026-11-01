import requests
from django.conf import settings


class BankAClient:

    def __init__(self):
        self.base_url = settings.BANK_A_BASE_URL
        self.timeout = settings.BANK_REQUEST_TIMEOUT

    def reserve_funds(self, account_id, transfer_id, amount):
        url = f"{self.base_url}/api/transfers/reserve/"

        response = requests.post(
            url,
            json={
                "account_id": str(account_id),
                "transfer_id": str(transfer_id),
                "amount": str(amount),
            },
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def commit_reservation(self, transfer_id):
        url = f"{self.base_url}/api/transfers/commit/"

        response = requests.post(
            url,
            json={
                "transfer_id": str(transfer_id)
            },
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def release_reservation(self, transfer_id):
        url = f"{self.base_url}/api/transfers/release/"

        response = requests.post(
            url,
            json={
                "transfer_id": str(transfer_id)
            },
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

    def get_transfer_status(self, transfer_id):
        url = f"{self.base_url}/api/transfers/{transfer_id}/status/"

        response = requests.get(
            url,
            timeout=self.timeout
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        return response.json()["data"]