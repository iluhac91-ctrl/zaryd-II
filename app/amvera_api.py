import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AMVERA_BASE_URL = "https://zaradki-ilyachur.amvera.io"

def auth_user_via_amvera(phone: str, pin: str):
    response = requests.post(
        f"{AMVERA_BASE_URL}/api/user-auth",
        data={
            "phone": phone,
            "pin": pin,
        },
        timeout=20,
        verify=False,
    )
    return response.json()
