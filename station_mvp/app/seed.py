from .database import SessionLocal, engine, Base
from .models import Slot


def seed_slots():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    existing = db.query(Slot).count()
    if existing == 0:
        slots = [
            Slot(slot_number=1, relay_channel=1, status="available"),
            Slot(slot_number=2, relay_channel=2, status="available"),
            Slot(slot_number=3, relay_channel=3, status="available"),
            Slot(slot_number=4, relay_channel=4, status="empty"),
        ]
        db.add_all(slots)
        db.commit()
        print("Слоты созданы")
    else:
        print("Слоты уже есть")

    db.close()