import json
from pathlib import Path

CONFIG_PATH = Path("/home/pi/station_mvp/config.json")


def load_config():
    if not CONFIG_PATH.exists():
        return {
            "station_id": "station_001",
            "station_name": "Zaryd Test Station",
            "station_address": "Тестовая локация",
            "service_mode": False
        }

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(data: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
