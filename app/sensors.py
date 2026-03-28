try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except Exception:
    GPIO_AVAILABLE = False


DOOR_SENSOR_PINS = {
    1: 5,
}


class SensorController:
    def __init__(self):
        self.enabled = GPIO_AVAILABLE

        if self.enabled:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)

            for pin in DOOR_SENSOR_PINS.values():
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def get_raw_state(self, slot_number: int):
        pin = DOOR_SENSOR_PINS.get(slot_number)
        if pin is None or not self.enabled:
            return None
        return GPIO.input(pin)

    def is_door_closed(self, slot_number: int) -> bool:
        raw = self.get_raw_state(slot_number)
        if raw is None:
            return False
        return raw == GPIO.LOW

    def is_door_open(self, slot_number: int) -> bool:
        return not self.is_door_closed(slot_number)

    def get_all_doors(self) -> dict:
        result = {}
        for slot_number in DOOR_SENSOR_PINS.keys():
            result[slot_number] = {
                "closed": self.is_door_closed(slot_number),
                "raw": self.get_raw_state(slot_number),
                "pin": DOOR_SENSOR_PINS[slot_number],
            }
        return result


sensor_controller = SensorController()
