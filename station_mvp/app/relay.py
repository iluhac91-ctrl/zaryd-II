import time

USE_GPIO = True

try:
    import RPi.GPIO as GPIO
except Exception:
    USE_GPIO = False


# Сопоставление каналов реле с GPIO пинами Raspberry Pi
# ПРИМЕР. Потом подстроим под твое реальное подключение.
RELAY_PINS = {
    1: 17,
    2: 27,
    3: 22,
    4: 23,
}


class RelayController:
    def __init__(self):
        self.gpio_enabled = USE_GPIO
        if self.gpio_enabled:
            GPIO.setmode(GPIO.BCM)
            for pin in RELAY_PINS.values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)  
                # часто реле active-low
                # HIGH = выключено, LOW = включено

    def open_slot(self, relay_channel: int, seconds: float = 1.0):
        pin = RELAY_PINS.get(relay_channel)
        if pin is None:
            raise ValueError(f"Неизвестный relay_channel: {relay_channel}")

        if self.gpio_enabled:
            print(f"[GPIO] Открываю канал {relay_channel}, pin={pin}")
            GPIO.output(pin, GPIO.LOW)
            time.sleep(seconds)
            GPIO.output(pin, GPIO.HIGH)
        else:
            print(f"[SIMULATION] Открываю канал {relay_channel} на {seconds} сек")

    def cleanup(self):
        if self.gpio_enabled:
            GPIO.cleanup()


relay_controller = RelayController()