from pathlib import Path
import os
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PUBLIC_ID = os.getenv("CLOUDPAYMENTS_PUBLIC_ID", "").strip()
API_SECRET = os.getenv("CLOUDPAYMENTS_API_SECRET", "").strip()
CURRENCY = os.getenv("CLOUDPAYMENTS_CURRENCY", "RUB").strip() or "RUB"

API_AUTH_URL = "https://api.cloudpayments.ru/payments/cards/auth"
API_TOKEN_CHARGE_URL = "https://api.cloudpayments.ru/payments/tokens/charge"


def make_test_charge(
    cryptogram: str,
    amount: float,
    account_id: str,
    description: str,
    email: str = "",
    ip_address: str = "127.0.0.1",
):
    payload = {
        "Amount": amount,
        "Currency": CURRENCY,
        "IpAddress": ip_address,
        "Name": "TEST TEST",
        "CardCryptogramPacket": cryptogram,
        "AccountId": account_id,
        "Description": description,
        "InvoiceId": account_id,
    }

    if email:
        payload["Email"] = email

    response = requests.post(
        API_AUTH_URL,
        json=payload,
        auth=(PUBLIC_ID, API_SECRET),
        timeout=40,
    )

    try:
        return response.json()
    except Exception:
        return {
            "Success": False,
            "Message": "CloudPayments вернул не-JSON ответ",
            "RawText": response.text,
            "StatusCode": response.status_code,
        }


def charge_by_token(token: str, amount: float, invoice_id: str, account_id: str):
    payload = {
        "Token": token,
        "Amount": amount,
        "Currency": CURRENCY,
        "InvoiceId": invoice_id,
        "AccountId": account_id,
        "Description": "IIBOX charge"
    }

    response = requests.post(
        API_TOKEN_CHARGE_URL,
        json=payload,
        auth=(PUBLIC_ID, API_SECRET),
        timeout=40,
    )

    try:
        return response.json()
    except Exception:
        return {
            "Success": False,
            "Message": "CloudPayments вернул не-JSON ответ",
            "RawText": response.text,
            "StatusCode": response.status_code,
        }
