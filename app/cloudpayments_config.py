from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CLOUDPAYMENTS_PUBLIC_ID = os.getenv("CLOUDPAYMENTS_PUBLIC_ID", "").strip()
CLOUDPAYMENTS_API_SECRET = os.getenv("CLOUDPAYMENTS_API_SECRET", "").strip()
CLOUDPAYMENTS_CURRENCY = os.getenv("CLOUDPAYMENTS_CURRENCY", "RUB").strip() or "RUB"
