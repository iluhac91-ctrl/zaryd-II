import qrcode
from pathlib import Path

BASE_URL = "http://192.168.1.69:8001"

routes = {
    "qr_take_mobile.png": f"{BASE_URL}/take",
    "qr_return_mobile.png": f"{BASE_URL}/return",
}

output_dir = Path("/home/pi/station_mvp/app/static/qr")
output_dir.mkdir(parents=True, exist_ok=True)

for filename, url in routes.items():
    img = qrcode.make(url)
    img.save(output_dir / filename)
    print(f"Created: {output_dir / filename} -> {url}")
