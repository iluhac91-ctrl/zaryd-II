import os

ON_RENDER = os.getenv("RENDER", "").lower() == "true" or os.getenv("PORT") is not None


class DummyRelayController:
    def open_slot(self, relay_channel, seconds=1.0):
        print(f"[DUMMY RELAY] open_slot relay_channel={relay_channel} seconds={seconds}")


class DummySensorController:
    def is_door_open(self, slot_number: int) -> bool:
        return False

    def is_door_closed(self, slot_number: int) -> bool:
        return True

    def get_all_doors(self):
        return {1: True, 2: True, 3: True, 4: True}
