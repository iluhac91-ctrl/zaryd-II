from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from .database import Base, engine, get_db
from .models import User, Slot, Rental
from .relay import relay_controller
from .seed import seed_slots

app = FastAPI(title="Charging Station MVP")

Base.metadata.create_all(bind=engine)
seed_slots()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("8") and len(phone) == 11:
        phone = "+7" + phone[1:]
    elif phone.startswith("7") and len(phone) == 11:
        phone = "+" + phone
    elif not phone.startswith("+"):
        phone = "+" + phone
    return phone


def hash_pin(pin: str) -> str:
    return pwd_context.hash(pin)


def verify_pin(pin: str, pin_hash: str) -> bool:
    return pwd_context.verify(pin, pin_hash)


def get_available_slot_for_take(db: Session):
    return db.query(Slot).filter(Slot.status == "available").order_by(Slot.slot_number).first()


def get_available_slot_for_return(db: Session):
    return db.query(Slot).filter(Slot.status == "empty").order_by(Slot.slot_number).first()


def get_active_rental(db: Session, user_id: int):
    return db.query(Rental).filter(
        Rental.user_id == user_id,
        Rental.status == "active"
    ).first()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    slots = db.query(Slot).order_by(Slot.slot_number).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "slots": slots
    })


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register", response_class=HTMLResponse)
def register_user(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db)
):
    phone = normalize_phone(phone)

    existing = db.query(User).filter(User.phone == phone).first()
    if existing:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Ошибка",
            "message": "Пользователь с таким номером уже существует."
        })

    user = User(
        phone=phone,
        pin_hash=hash_pin(pin)
    )
    db.add(user)
    db.commit()

    return templates.TemplateResponse("message.html", {
        "request": request,
        "title": "Успех",
        "message": f"Пользователь {phone} зарегистрирован."
    })


@app.get("/take", response_class=HTMLResponse)
def take_page(request: Request):
    return templates.TemplateResponse("take.html", {"request": request})


@app.post("/take", response_class=HTMLResponse)
def take_powerbank(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db)
):
    phone = normalize_phone(phone)
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Ошибка",
            "message": "Пользователь не найден. Сначала зарегистрируйтесь."
        })

    if not verify_pin(pin, user.pin_hash):
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Ошибка",
            "message": "Неверный PIN."
        })

    active_rental = get_active_rental(db, user.id)
    if active_rental:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Ошибка",
            "message": f"У вас уже есть активная аренда. Слот выдачи: {active_rental.slot_number}"
        })

    slot = get_available_slot_for_take(db)
    if not slot:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Нет зарядов",
            "message": "Сейчас нет доступных powerbank."
        })

    relay_controller.open_slot(slot.relay_channel, seconds=1.0)

    rental = Rental(
        user_id=user.id,
        slot_number=slot.slot_number,
        status="active"
    )
    db.add(rental)

    slot.status = "rented"
    db.commit()

    return templates.TemplateResponse("message.html", {
        "request": request,
        "title": "Заряд выдан",
        "message": f"Открыта ячейка №{slot.slot_number}. Заберите powerbank."
    })


@app.get("/return", response_class=HTMLResponse)
def return_page(request: Request):
    return templates.TemplateResponse("return.html", {"request": request})


@app.post("/return", response_class=HTMLResponse)
def return_powerbank(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db)
):
    phone = normalize_phone(phone)
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Ошибка",
            "message": "Пользователь не найден."
        })

    if not verify_pin(pin, user.pin_hash):
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Ошибка",
            "message": "Неверный PIN."
        })

    active_rental = get_active_rental(db, user.id)
    if not active_rental:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Нет аренды",
            "message": "У вас нет активной аренды."
        })

    return_slot = get_available_slot_for_return(db)
    if not return_slot:
        return templates.TemplateResponse("message.html", {
            "request": request,
            "title": "Нет свободных ячеек",
            "message": "На станции нет свободной ячейки для возврата."
        })

    relay_controller.open_slot(return_slot.relay_channel, seconds=1.0)

    rented_slot = db.query(Slot).filter(Slot.slot_number == active_rental.slot_number).first()
    if rented_slot:
        rented_slot.status = "empty"

    return_slot.status = "available"
    active_rental.status = "returned"
    active_rental.end_time = datetime.utcnow()

    db.commit()

    return templates.TemplateResponse("message.html", {
        "request": request,
        "title": "Возврат завершен",
        "message": f"Открыта ячейка №{return_slot.slot_number}. Вставьте powerbank и закройте дверцу."
    })