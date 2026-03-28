from pathlib import Path
import os
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PUBLIC_ID = os.getenv("CLOUDPAYMENTS_PUBLIC_ID", "").strip()
API_PUBLIC_KEY = os.getenv("CLOUDPAYMENTS_API_PUBLIC_KEY", "").strip()
API_SECRET = os.getenv("CLOUDPAYMENTS_API_SECRET", "").strip()
CURRENCY = os.getenv("CLOUDPAYMENTS_CURRENCY", "RUB").strip() or "RUB"

API_URL = "https://api.cloudpayments.ru/payments/cards/auth"


def make_test_charge(cryptogram: str, amount: float, account_id: str, description: str, email: str = ""):
    payload = {
        "Amount": amount,
        "Currency": CURRENCY,
        "Name": "TEST TEST",
        "CardCryptogramPacket": cryptogram,
        "AccountId": account_id,
        "Description": description,
    }

    if email:
        payload["Email"] = email

    response = requests.post(
        API_URL,
        json=payload,
        auth=(API_PUBLIC_KEY, API_SECRET),
        timeout=40,
    )

    try:
        data = response.json()
    except Exception:
        data = {
            "Success": False,
            "Message": "CloudPayments вернул не-JSON ответ",
            "RawText": response.text,
            "StatusCode": response.status_code,
        }

    return {
        "status_code": response.status_code,
        "data": data,
    }
