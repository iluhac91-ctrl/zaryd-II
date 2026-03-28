import qrcode
from pathlib import Path

BASE_URL = "http://192.168.1.69:8001"

routes = {
    "qr_main.png": f"{BASE_URL}/scan",
}

output_dir = Path("qr_codes")
output_dir.mkdir(exist_ok=True)

for filename, url in routes.items():
    img = qrcode.make(url)
    img.save(output_dir / filename)
    print(f"Created: {output_dir / filename} -> {url}")
