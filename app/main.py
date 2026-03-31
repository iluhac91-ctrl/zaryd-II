from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form, Depends, Body, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from .database import Base, engine, get_db
from .models import User, Slot, Rental, EventLog
try:
    from .relay import relay_controller
except Exception:
    relay_controller = None
from .seed import seed_slots
try:
    from .sensors import sensor_controller
except Exception:
    sensor_controller = None
from .config import load_config, save_config
from .cloudpayments_api import make_test_charge, charge_by_token
from .cloudpayments_config import CLOUDPAYMENTS_PUBLIC_ID, CLOUDPAYMENTS_CURRENCY

from .render_hardware import ON_RENDER, DummyRelayController, DummySensorController

if ON_RENDER:
    relay_controller = DummyRelayController()
    sensor_controller = DummySensorController()


app = FastAPI(title="Charging Station MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://beautiful-stardust-c61b83.netlify.app",
        "https://zesty-syrniki-a16777.netlify.app",
        "https://zaradki-ilyachur.amvera.io",
        "http://127.0.0.1:8001",
        "http://192.168.1.69:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


Base.metadata.create_all(bind=engine)
seed_slots()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/site", StaticFiles(directory="public_site", html=True), name="site_public")
templates = Jinja2Templates(directory="app/templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ISSUE_TIMEOUT_SECONDS = 20
RETURN_TIMEOUT_SECONDS = 20

DOOR_NOT_OPEN_WARN_SECONDS = 8
FAST_DOOR_CYCLE_SECONDS = 1.2
SLOW_DOOR_CYCLE_SECONDS = 15


def now_utc():
    return datetime.now(timezone.utc)


def normalize_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_home_url(ui: str):
    return "/kiosk" if ui == "kiosk" else "/web"


def render_message(
    request: Request,
    title: str,
    message: str,
    ui: str = "web",
    is_error: bool = False,
):
    template = "message.html"
    if ui == "kiosk":
        template = "kiosk_error.html" if is_error else "kiosk_success.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "request": request,
            "title": title,
            "message": message,
            "home_url": get_home_url(ui),
        },
    )


def render_wait_open(
    request: Request,
    slot_number: int,
    door_open: bool,
    next_url: str | None,
    refresh_url: str,
    title: str,
    description: str,
    ui: str = "web",
):
    template = "kiosk_wait_open.html" if ui == "kiosk" else "wait_door_open.html"
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "request": request,
            "slot_number": slot_number,
            "door_open": door_open,
            "next_url": next_url,
            "refresh_url": refresh_url,
            "title": title,
            "description": description,
            "home_url": get_home_url(ui),
        },
    )


def render_wait_close(
    request: Request,
    slot_number: int,
    door_closed: bool,
    next_url: str | None,
    refresh_url: str,
    title: str,
    description: str,
    ui: str = "web",
):
    template = "kiosk_wait_close.html" if ui == "kiosk" else "wait_door_close.html"
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "request": request,
            "slot_number": slot_number,
            "door_closed": door_closed,
            "next_url": next_url,
            "refresh_url": refresh_url,
            "title": title,
            "description": description,
            "home_url": get_home_url(ui),
        },
    )


def log_event(
    db: Session,
    event_type: str,
    message: str,
    user_phone: str | None = None,
    slot_number: int | None = None,
    rental_id: int | None = None,
):
    event = EventLog(
        event_type=event_type,
        message=message,
        user_phone=user_phone,
        slot_number=slot_number,
        rental_id=rental_id,
    )
    db.add(event)
    db.commit()


def has_event(db: Session, event_type: str, rental_id: int) -> bool:
    return db.query(EventLog).filter(
        EventLog.event_type == event_type,
        EventLog.rental_id == rental_id
    ).first() is not None


def get_event(db: Session, event_type: str, rental_id: int):
    return db.query(EventLog).filter(
        EventLog.event_type == event_type,
        EventLog.rental_id == rental_id
    ).order_by(EventLog.id.asc()).first()


def log_event_once(
    db: Session,
    event_type: str,
    message: str,
    user_phone: str | None = None,
    slot_number: int | None = None,
    rental_id: int | None = None,
):
    if rental_id is not None and has_event(db, event_type, rental_id):
        return
    log_event(
        db=db,
        event_type=event_type,
        message=message,
        user_phone=user_phone,
        slot_number=slot_number,
        rental_id=rental_id,
    )


def mark_suspicious(
    db: Session,
    code: str,
    message: str,
    user_phone: str | None = None,
    slot_number: int | None = None,
    rental_id: int | None = None,
):
    log_event_once(
        db=db,
        event_type=code,
        message=message,
        user_phone=user_phone,
        slot_number=slot_number,
        rental_id=rental_id,
    )


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


def cleanup_expired_operations(db: Session):
    rentals = db.query(Rental).filter(Rental.status.in_(["issuing", "returning"])).all()
    current_time = now_utc()

    for rental in rentals:
        started = normalize_dt(rental.start_time)
        if started is None:
            continue

        age = (current_time - started).total_seconds()
        slot = db.query(Slot).filter(Slot.slot_number == rental.slot_number).first()
        if not slot:
            continue

        user = db.query(User).filter(User.id == rental.user_id).first()
        user_phone = user.phone if user else None

        if rental.status == "issuing" and age > ISSUE_TIMEOUT_SECONDS:
            rental.status = "cancelled"
            rental.end_time = current_time
            slot.status = "available"
            db.commit()
            log_event_once(
                db,
                "issue_timeout",
                f"Выдача отменена по таймауту. Слот {slot.slot_number}.",
                user_phone=user_phone,
                slot_number=slot.slot_number,
                rental_id=rental.id,
            )

        elif rental.status == "returning" and age > RETURN_TIMEOUT_SECONDS:
            rental.status = "active"
            slot.status = "empty"
            db.commit()
            log_event_once(
                db,
                "return_timeout",
                f"Возврат отменен по таймауту. Слот {slot.slot_number}.",
                user_phone=user_phone,
                slot_number=slot.slot_number,
                rental_id=rental.id,
            )


def get_available_slot_for_take(db: Session):
    return db.query(Slot).filter(Slot.status == "available").order_by(Slot.slot_number).first()


def get_available_slot_for_return(db: Session):
    return db.query(Slot).filter(Slot.status == "empty").order_by(Slot.slot_number).first()


def get_user_active_rental(db: Session, user_id: int):
    return db.query(Rental).filter(
        Rental.user_id == user_id,
        Rental.status.in_(["issuing", "active", "returning"])
    ).order_by(Rental.id.desc()).first()


@app.get("/", response_class=HTMLResponse)
def idle_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_idle.html",
        context={"request": request},
    )



@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"request": request},
    )

@app.get("/web", response_class=HTMLResponse)
def web_index(request: Request, db: Session = Depends(get_db)):
    cleanup_expired_operations(db)
    cfg = load_config()
    slots = db.query(Slot).order_by(Slot.slot_number).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "slots": slots,
            "station_name": cfg.get("station_name", "IIBOX"),
            "station_address": cfg.get("station_address", ""),
            "service_mode": cfg.get("service_mode", False),
        },
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"request": request},
    )


@app.post("/register", response_class=HTMLResponse)
def register_user(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    ui: str = Form("web"),
    db: Session = Depends(get_db),
):
    phone = normalize_phone(phone)

    existing = db.query(User).filter(User.phone == phone).first()
    if existing:
        log_event(
            db,
            "register_duplicate",
            f"Попытка повторной регистрации номера {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Ошибка",
            "Пользователь с таким номером уже существует.",
            ui=ui,
            is_error=True,
        )

    user = User(phone=phone, pin_hash=hash_pin(pin))
    db.add(user)
    db.commit()

    log_event(
        db,
        "register_success",
        f"Пользователь зарегистрирован: {phone}.",
        user_phone=phone,
    )

    return render_message(
        request,
        "Успех",
        f"Пользователь {phone} зарегистрирован.",
        ui=ui,
        is_error=False,
    )


@app.get("/take", response_class=HTMLResponse)
def take_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="take.html",
        context={"request": request},
    )


@app.post("/take", response_class=HTMLResponse)
def take_powerbank(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    ui: str = Form("web"),
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    cfg = load_config()
    if cfg.get("service_mode", False):
        return render_message(
            request,
            "Станция на обслуживании",
            "Станция временно недоступна.",
            ui=ui,
            is_error=True,
        )

    phone = normalize_phone(phone)
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        log_event(
            db,
            "take_user_not_found",
            f"Попытка взять заряд для несуществующего пользователя {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Ошибка",
            "Пользователь не найден. Сначала зарегистрируйтесь.",
            ui=ui,
            is_error=True,
        )

    if not verify_pin(pin, user.pin_hash):
        log_event(
            db,
            "take_bad_pin",
            f"Неверный PIN при попытке выдачи для {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Ошибка",
            "Неверный PIN.",
            ui=ui,
            is_error=True,
        )

    active_rental = get_user_active_rental(db, user.id)
    if active_rental and active_rental.status in ["issuing", "active", "returning"]:
        log_event(
            db,
            "take_blocked_active_rental",
            f"Выдача заблокирована: у пользователя {phone} уже есть операция {active_rental.status}.",
            user_phone=phone,
            slot_number=active_rental.slot_number,
            rental_id=active_rental.id,
        )
        return render_message(
            request,
            "Ошибка",
            f"У вас уже есть активная операция. Статус: {active_rental.status}, слот: {active_rental.slot_number}",
            ui=ui,
            is_error=True,
        )

    slot = get_available_slot_for_take(db)
    if not slot:
        log_event(
            db,
            "take_no_slots",
            f"Нет доступных зарядов для пользователя {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Нет зарядов",
            "Сейчас нет доступных powerbank.",
            ui=ui,
            is_error=True,
        )

    
# ===== 💳 ОПЛАТА ПЕРЕД ВЫДАЧЕЙ =====

    


    rental = Rental(
        user_id=user.id,
        slot_number=slot.slot_number,
        status="issuing",
        start_time=now_utc(),
    )
    db.add(rental)
    slot.status = "issuing"
    db.commit()
    db.refresh(rental)

    log_event(
        db,
        "take_started",
        f"Начата выдача пользователю {phone}. Слот {slot.slot_number}.",
        user_phone=phone,
        slot_number=slot.slot_number,
        rental_id=rental.id,
    )

    return RedirectResponse(
        url=f"/take/wait-door-open?rental_id={rental.id}&ui={ui}",
        status_code=303,
    )


@app.get("/take/wait-door-open", response_class=HTMLResponse)
def wait_take_door_open(
    request: Request,
    rental_id: int,
    ui: str = "web",
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if not rental or rental.status != "issuing":
        return render_message(
            request,
            "Операция недоступна",
            "Выдача уже завершена или отменена.",
            ui=ui,
            is_error=True,
        )

    user = db.query(User).filter(User.id == rental.user_id).first()
    user_phone = user.phone if user else None

    door_open = sensor_controller.is_door_open(rental.slot_number)
    started = normalize_dt(rental.start_time)
    if started:
        age = (now_utc() - started).total_seconds()
        if not door_open and age > DOOR_NOT_OPEN_WARN_SECONDS:
            mark_suspicious(
                db,
                "suspicious_take_no_open",
                f"Подозрение: при выдаче дверца долго не открывается. Слот {rental.slot_number}.",
                user_phone=user_phone,
                slot_number=rental.slot_number,
                rental_id=rental.id,
            )

    if door_open:
        log_event_once(
            db,
            "take_door_opened",
            f"При выдаче дверца открыта. Слот {rental.slot_number}.",
            user_phone=user_phone,
            slot_number=rental.slot_number,
            rental_id=rental.id,
        )

    return render_wait_open(
        request=request,
        slot_number=rental.slot_number,
        door_open=door_open,
        next_url=f"/take/wait-door-close?rental_id={rental.id}&ui={ui}" if door_open else None,
        refresh_url=f"/take/wait-door-open?rental_id={rental.id}&ui={ui}",
        title="Ожидание открытия дверцы",
        description="Откройте дверцу ячейки.",
        ui=ui,
    )


@app.get("/take/wait-door-close", response_class=HTMLResponse)
def wait_take_door_close(
    request: Request,
    rental_id: int,
    ui: str = "web",
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if not rental or rental.status != "issuing":
        return render_message(
            request,
            "Операция недоступна",
            "Выдача уже завершена или отменена.",
            ui=ui,
            is_error=True,
        )

    user = db.query(User).filter(User.id == rental.user_id).first()
    user_phone = user.phone if user else None

    door_closed = sensor_controller.is_door_closed(rental.slot_number)
    open_event = get_event(db, "take_door_opened", rental.id)

    if door_closed and open_event:
        log_event_once(
            db,
            "take_door_closed",
            f"При выдаче дверца снова закрыта. Слот {rental.slot_number}.",
            user_phone=user_phone,
            slot_number=rental.slot_number,
            rental_id=rental.id,
        )

        opened_at = normalize_dt(open_event.created_at)
        if opened_at:
            cycle = (now_utc() - opened_at).total_seconds()

            if cycle < FAST_DOOR_CYCLE_SECONDS:
                mark_suspicious(
                    db,
                    "suspicious_take_fast_cycle",
                    f"Подозрение: слишком быстрое открытие/закрытие при выдаче ({cycle:.2f} сек). Слот {rental.slot_number}.",
                    user_phone=user_phone,
                    slot_number=rental.slot_number,
                    rental_id=rental.id,
                )

            if cycle > SLOW_DOOR_CYCLE_SECONDS:
                mark_suspicious(
                    db,
                    "suspicious_take_slow_cycle",
                    f"Подозрение: дверца слишком долго была открыта при выдаче ({cycle:.2f} сек). Слот {rental.slot_number}.",
                    user_phone=user_phone,
                    slot_number=rental.slot_number,
                    rental_id=rental.id,
                )

    return render_wait_close(
        request=request,
        slot_number=rental.slot_number,
        door_closed=door_closed,
        next_url=f"/take/confirm-sensor?rental_id={rental.id}&ui={ui}" if door_closed else None,
        refresh_url=f"/take/wait-door-close?rental_id={rental.id}&ui={ui}",
        title="Ожидание закрытия дверцы",
        description="Закройте дверцу после того, как забрали powerbank.",
        ui=ui,
    )


@app.get("/take/confirm-sensor", response_class=HTMLResponse)
def confirm_take_sensor(
    request: Request,
    rental_id: int,
    ui: str = "web",
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if not rental or rental.status != "issuing":
        return render_message(
            request,
            "Операция недоступна",
            "Выдача уже завершена или отменена.",
            ui=ui,
            is_error=True,
        )

    slot = db.query(Slot).filter(Slot.slot_number == rental.slot_number).first()
    user = db.query(User).filter(User.id == rental.user_id).first()
    user_phone = user.phone if user else None

    if slot:
        slot.status = "rented"

    rental.status = "active"
    rental.start_time = now_utc()
    db.commit()

    log_event(
        db,
        "take_confirmed_sensor",
        f"Выдача подтверждена датчиком/дверцей. Слот {rental.slot_number}.",
        user_phone=user_phone,
        slot_number=rental.slot_number,
        rental_id=rental.id,
    )

    return render_message(
        request,
        "Заряд выдан",
        f"Дверца ячейки №{rental.slot_number} открывалась и снова закрылась. Выдача завершена.",
        ui=ui,
        is_error=False,
    )


@app.get("/return", response_class=HTMLResponse)
def return_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="return.html",
        context={"request": request},
    )


@app.post("/return", response_class=HTMLResponse)
def return_powerbank(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    ui: str = Form("web"),
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    cfg = load_config()
    if cfg.get("service_mode", False):
        return render_message(
            request,
            "Станция на обслуживании",
            "Станция временно недоступна.",
            ui=ui,
            is_error=True,
        )

    phone = normalize_phone(phone)
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        log_event(
            db,
            "return_user_not_found",
            f"Попытка возврата для несуществующего пользователя {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Ошибка",
            "Пользователь не найден.",
            ui=ui,
            is_error=True,
        )

    if not verify_pin(pin, user.pin_hash):
        log_event(
            db,
            "return_bad_pin",
            f"Неверный PIN при попытке возврата для {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Ошибка",
            "Неверный PIN.",
            ui=ui,
            is_error=True,
        )

    active_rental = db.query(Rental).filter(
        Rental.user_id == user.id,
        Rental.status == "active"
    ).order_by(Rental.id.desc()).first()

    if not active_rental:
        log_event(
            db,
            "return_no_active_rental",
            f"Нет активной аренды для возврата у пользователя {phone}.",
            user_phone=phone,
        )
        return render_message(
            request,
            "Нет аренды",
            "У вас нет активной аренды.",
            ui=ui,
            is_error=True,
        )

    return_slot = get_available_slot_for_return(db)
    if not return_slot:
        log_event(
            db,
            "return_no_empty_slot",
            f"Нет свободного слота для возврата у пользователя {phone}.",
            user_phone=phone,
            rental_id=active_rental.id,
        )
        return render_message(
            request,
            "Нет свободных ячеек",
            "На станции нет свободной ячейки для возврата.",
            ui=ui,
            is_error=True,
        )

    relay_controller.open_slot(return_slot.relay_channel, seconds=1.0)

    rented_slot = db.query(Slot).filter(Slot.slot_number == active_rental.slot_number).first()
    if rented_slot:
        rented_slot.status = "empty"

    return_slot.status = "returning"
    active_rental.slot_number = return_slot.slot_number
    active_rental.status = "returning"
    active_rental.start_time = now_utc()
    db.commit()

    log_event(
        db,
        "return_started",
        f"Начат возврат пользователем {phone}. Слот {return_slot.slot_number}.",
        user_phone=user_phone,
        slot_number=return_slot.slot_number,
        rental_id=active_rental.id,
    )

    return RedirectResponse(
        url=f"/return/wait-door-open?rental_id={active_rental.id}&ui={ui}",
        status_code=303,
    )


@app.get("/return/wait-door-open", response_class=HTMLResponse)
def wait_return_door_open(
    request: Request,
    rental_id: int,
    ui: str = "web",
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if not rental or rental.status != "returning":
        return render_message(
            request,
            "Операция недоступна",
            "Возврат уже завершен или отменен.",
            ui=ui,
            is_error=True,
        )

    user = db.query(User).filter(User.id == rental.user_id).first()
    user_phone = user.phone if user else None

    door_open = sensor_controller.is_door_open(rental.slot_number)
    started = normalize_dt(rental.start_time)
    if started:
        age = (now_utc() - started).total_seconds()
        if not door_open and age > DOOR_NOT_OPEN_WARN_SECONDS:
            mark_suspicious(
                db,
                "suspicious_return_no_open",
                f"Подозрение: при возврате дверца долго не открывается. Слот {rental.slot_number}.",
                user_phone=user_phone,
                slot_number=rental.slot_number,
                rental_id=rental.id,
            )

    if door_open:
        log_event_once(
            db,
            "return_door_opened",
            f"При возврате дверца открыта. Слот {rental.slot_number}.",
            user_phone=user_phone,
            slot_number=rental.slot_number,
            rental_id=rental.id,
        )

    return render_wait_open(
        request=request,
        slot_number=rental.slot_number,
        door_open=door_open,
        next_url=f"/return/wait-door-close?rental_id={rental.id}&ui={ui}" if door_open else None,
        refresh_url=f"/return/wait-door-open?rental_id={rental.id}&ui={ui}",
        title="Ожидание открытия дверцы",
        description="Откройте дверцу ячейки для возврата.",
        ui=ui,
    )


@app.get("/return/wait-door-close", response_class=HTMLResponse)
def wait_return_door_close(
    request: Request,
    rental_id: int,
    ui: str = "web",
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if not rental or rental.status != "returning":
        return render_message(
            request,
            "Операция недоступна",
            "Возврат уже завершен или отменен.",
            ui=ui,
            is_error=True,
        )

    user = db.query(User).filter(User.id == rental.user_id).first()
    user_phone = user.phone if user else None

    door_closed = sensor_controller.is_door_closed(rental.slot_number)
    open_event = get_event(db, "return_door_opened", rental.id)

    if door_closed and open_event:
        log_event_once(
            db,
            "return_door_closed",
            f"При возврате дверца снова закрыта. Слот {rental.slot_number}.",
            user_phone=user_phone,
            slot_number=rental.slot_number,
            rental_id=rental.id,
        )

        opened_at = normalize_dt(open_event.created_at)
        if opened_at:
            cycle = (now_utc() - opened_at).total_seconds()

            if cycle < FAST_DOOR_CYCLE_SECONDS:
                mark_suspicious(
                    db,
                    "suspicious_return_fast_cycle",
                    f"Подозрение: слишком быстрое открытие/закрытие при возврате ({cycle:.2f} сек). Слот {rental.slot_number}.",
                    user_phone=user_phone,
                    slot_number=rental.slot_number,
                    rental_id=rental.id,
                )

            if cycle > SLOW_DOOR_CYCLE_SECONDS:
                mark_suspicious(
                    db,
                    "suspicious_return_slow_cycle",
                    f"Подозрение: дверца слишком долго была открыта при возврате ({cycle:.2f} сек). Слот {rental.slot_number}.",
                    user_phone=user_phone,
                    slot_number=rental.slot_number,
                    rental_id=rental.id,
                )

    return render_wait_close(
        request=request,
        slot_number=rental.slot_number,
        door_closed=door_closed,
        next_url=f"/return/confirm-sensor?rental_id={rental.id}&ui={ui}" if door_closed else None,
        refresh_url=f"/return/wait-door-close?rental_id={rental.id}&ui={ui}",
        title="Ожидание закрытия дверцы",
        description="Вставьте powerbank, закройте дверцу.",
        ui=ui,
    )


@app.get("/return/confirm-sensor", response_class=HTMLResponse)
def confirm_return_sensor(
    request: Request,
    rental_id: int,
    ui: str = "web",
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if not rental or rental.status != "returning":
        return render_message(
            request,
            "Операция недоступна",
            "Возврат уже завершен или отменен.",
            ui=ui,
            is_error=True,
        )

    slot = db.query(Slot).filter(Slot.slot_number == rental.slot_number).first()
    user = db.query(User).filter(User.id == rental.user_id).first()
    user_phone = user.phone if user else None

    if slot:
        slot.status = "available"

    rental.status = "returned"
    rental.end_time = now_utc()
    db.commit()

    log_event(
        db,
        "return_confirmed_sensor",
        f"Возврат подтвержден датчиком/дверцей. Слот {rental.slot_number}.",
        user_phone=user_phone,
        slot_number=rental.slot_number,
        rental_id=rental.id,
    )

    return render_message(
        request,
        "Возврат завершен",
        f"Дверца ячейки №{rental.slot_number} открывалась и снова закрылась. Возврат завершен.",
        ui=ui,
        is_error=False,
    )


@app.get("/kiosk", response_class=HTMLResponse)
def kiosk_page(request: Request, db: Session = Depends(get_db)):
    cleanup_expired_operations(db)
    cfg = load_config()
    slots = db.query(Slot).order_by(Slot.slot_number).all()

    available_count = sum(1 for s in slots if s.status == "available")
    empty_count = sum(1 for s in slots if s.status == "empty")

    return templates.TemplateResponse(
        request=request,
        name="kiosk_index.html",
        context={
            "request": request,
            "station_name": cfg.get("station_name", "IIBOX"),
            "station_address": cfg.get("station_address", ""),
            "service_mode": cfg.get("service_mode", False),
            "available_count": available_count,
            "empty_count": empty_count,
        },
    )


@app.get("/kiosk/take", response_class=HTMLResponse)
def kiosk_take_method_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_take_method.html",
        context={"request": request},
    )


@app.get("/kiosk/return", response_class=HTMLResponse)
def kiosk_return_method_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_return_method.html",
        context={"request": request},
    )


@app.get("/kiosk/take/manual", response_class=HTMLResponse)
def kiosk_take_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_take.html",
        context={"request": request},
    )


@app.get("/kiosk/return/manual", response_class=HTMLResponse)
def kiosk_return_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_return.html",
        context={"request": request},
    )


@app.get("/kiosk/register", response_class=HTMLResponse)
def kiosk_register_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_register.html",
        context={"request": request},
    )


@app.get("/kiosk/take/qr", response_class=HTMLResponse)
def kiosk_take_qr_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_take_qr.html",
        context={"request": request},
    )


@app.get("/kiosk/return/qr", response_class=HTMLResponse)
def kiosk_return_qr_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="kiosk_return_qr.html",
        context={"request": request},
    )


@app.post("/kiosk/register", response_class=HTMLResponse)
def kiosk_register_submit(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    return register_user(request=request, phone=phone, pin=pin, ui="kiosk", db=db)


@app.post("/kiosk/take/manual", response_class=HTMLResponse)
def kiosk_take_submit(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    return take_powerbank(request=request, phone=phone, pin=pin, ui="kiosk", db=db)


@app.post("/kiosk/return/manual", response_class=HTMLResponse)
def kiosk_return_submit(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    return return_powerbank(request=request, phone=phone, pin=pin, ui="kiosk", db=db)





@app.get("/pay-checkout-test", response_class=HTMLResponse)
def pay_checkout_test_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pay_checkout.html",
        context={
            "request": request,
            "public_id": CLOUDPAYMENTS_PUBLIC_ID,
            "currency": CLOUDPAYMENTS_CURRENCY,
        },
    )


@app.post("/pay-checkout-test-charge")
def pay_checkout_test_charge(payload: dict = Body(...), db: Session = Depends(get_db)):
    cryptogram = payload.get("cryptogram", "")
    amount = float(payload.get("amount", 0))
    account_id = payload.get("account_id", "")
    description = payload.get("description", "Тестовая аренда IIBOX")
    email = payload.get("email", "")

    print("=== CP REQUEST START ===")
    print("account_id:", account_id)
    print("amount:", amount)
    print("description:", description)
    print("email:", email)
    print("cryptogram_present:", bool(cryptogram))
    print("=== CP REQUEST END ===")

    result = make_test_charge(
        cryptogram=cryptogram,
        amount=amount,
        account_id=account_id,
        description=description,
        email=email,
    )

    print("=== CP RESPONSE START ===")
    print(result)
    print("=== CP RESPONSE END ===")

    if result.get("Success"):
        model = result.get("Model", {}) or {}
        token = model.get("Token")
        print("CP SUCCESS TOKEN:", token)

        if token and account_id:
            user = db.query(User).filter(User.phone == account_id).first()
            if user:
                user.payment_token = token
                db.commit()
                print("TOKEN SAVED FOR:", user.phone)
            else:
                print("USER NOT FOUND FOR TOKEN SAVE:", account_id)
        else:
            print("TOKEN MISSING OR ACCOUNT_ID EMPTY")
    else:
        model = result.get("Model", {}) or {}
        print("CP FAILED STATUS:", model.get("Status"))
        print("CP FAILED REASON:", model.get("Reason"))
        print("CP FAILED CARDHOLDER MESSAGE:", model.get("CardHolderMessage"))

    return result



@app.post("/cloudpayments/pay-notify")
async def cloudpayments_pay_notify(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()

    print("=== CP PAY NOTIFY START ===")
    print(payload)
    print("=== CP PAY NOTIFY END ===")

    success = payload.get("Success")
    account_id = payload.get("AccountId")
    token = payload.get("Token")
    card_last_four = payload.get("CardLastFour")
    card_type = payload.get("CardType")

    if success and account_id:
        user = db.query(User).filter(User.phone == account_id).first()
        if user:
            if token:
                user.payment_token = token
            if card_last_four:
                user.card_last_four = card_last_four
            if card_type:
                user.card_type = card_type
            db.commit()
            print("TOKEN SAVED FOR:", user.phone, user.payment_token)
        else:
            user = User(
                phone=account_id,
                pin_hash="autocreated_by_webhook"
            )
            if token:
                user.payment_token = token
            if card_last_four:
                user.card_last_four = card_last_four
            if card_type:
                user.card_type = card_type

            db.add(user)
            db.commit()
            print("USER AUTO-CREATED:", account_id)
    else:
        print("NOT SUCCESS OR ACCOUNT_ID EMPTY")

    return {"code": 0}

@app.get("/pay-widget", response_class=HTMLResponse)
def pay_widget_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pay_widget.html",
        context={
            "request": request,
            "public_id": CLOUDPAYMENTS_PUBLIC_ID,
            "currency": CLOUDPAYMENTS_CURRENCY,
        },
    )


@app.post("/save-token-debug")
def save_token_debug(payload: dict = Body(...), db: Session = Depends(get_db)):
    account_id = payload.get("account_id", "")
    print("=== SAVE TOKEN DEBUG START ===")
    print("ACCOUNT ID:", account_id)
    print("PAYLOAD:", payload)
    print("=== SAVE TOKEN DEBUG END ===")

    user = db.query(User).filter(User.phone == account_id).first()
    if not user:
        return {"ok": False, "message": "user_not_found", "account_id": account_id}

    return {"ok": True, "message": "callback_received", "account_id": account_id}

@app.get("/pay-test", response_class=HTMLResponse)
def pay_test_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pay_test.html",
        context={
            "request": request,
            "public_id": CLOUDPAYMENTS_PUBLIC_ID,
            "currency": CLOUDPAYMENTS_CURRENCY,
        },
    )

@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="scan.html",
        context={"request": request},
    )


@app.get("/my-rental", response_class=HTMLResponse)
def my_rental_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="my_rental_login.html",
        context={"request": request},
    )


@app.post("/my-rental", response_class=HTMLResponse)
def my_rental_result(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    cleanup_expired_operations(db)

    phone = normalize_phone(phone)
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        return render_message(
            request,
            "Пользователь не найден",
            "Пользователь с таким номером не найден.",
            ui="web",
            is_error=True,
        )

    if not verify_pin(pin, user.pin_hash):
        return render_message(
            request,
            "Ошибка",
            "Неверный PIN.",
            ui="web",
            is_error=True,
        )

    rental = db.query(Rental).filter(
        Rental.user_id == user.id,
        Rental.status.in_(["issuing", "active", "returning"])
    ).order_by(Rental.id.desc()).first()

    return templates.TemplateResponse(
        request=request,
        name="my_rental_view.html",
        context={
            "request": request,
            "user": user,
            "rental": rental,
        },
    )


@app.get("/service", response_class=HTMLResponse)
def service_page(request: Request, db: Session = Depends(get_db)):
    cfg = load_config()
    slots = db.query(Slot).order_by(Slot.slot_number).all()
    rentals = db.query(Rental).order_by(Rental.id.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="service.html",
        context={
            "request": request,
            "config": cfg,
            "slots": slots,
            "rentals": rentals,
        },
    )


@app.post("/service/toggle-mode")
def service_toggle_mode():
    cfg = load_config()
    cfg["service_mode"] = not cfg.get("service_mode", False)
    save_config(cfg)
    return RedirectResponse(url="/service", status_code=303)


@app.post("/service/update-config")
def service_update_config(
    station_name: str = Form(...),
    station_address: str = Form(...),
):
    cfg = load_config()
    cfg["station_name"] = station_name
    cfg["station_address"] = station_address
    save_config(cfg)
    return RedirectResponse(url="/service", status_code=303)


@app.post("/service/disable-slot")
def service_disable_slot(
    slot_number: int = Form(...),
    db: Session = Depends(get_db),
):
    slot = db.query(Slot).filter(Slot.slot_number == slot_number).first()
    if slot:
        slot.status = "disabled"
        db.commit()
    return RedirectResponse(url="/service", status_code=303)


@app.post("/service/enable-slot")
def service_enable_slot(
    slot_number: int = Form(...),
    db: Session = Depends(get_db),
):
    slot = db.query(Slot).filter(Slot.slot_number == slot_number).first()
    if slot:
        slot.status = "empty" if slot.slot_number == 4 else "available"
        db.commit()
    return RedirectResponse(url="/service", status_code=303)


@app.post("/service/finish-rental")
def service_finish_rental(
    rental_id: int = Form(...),
    db: Session = Depends(get_db),
):
    rental = db.query(Rental).filter(Rental.id == rental_id).first()
    if rental and rental.status in ["issuing", "active", "returning"]:
        rental.status = "returned"
        rental.end_time = now_utc()
        db.commit()
    return RedirectResponse(url="/service", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    cleanup_expired_operations(db)
    users = db.query(User).order_by(User.id.desc()).all()
    rentals = db.query(Rental).order_by(Rental.id.desc()).all()
    slots = db.query(Slot).order_by(Slot.slot_number).all()
    events = db.query(EventLog).order_by(EventLog.id.desc()).limit(100).all()
    suspicious_events = db.query(EventLog).filter(
        EventLog.event_type.like("suspicious_%")
    ).order_by(EventLog.id.desc()).limit(50).all()
    doors = sensor_controller.get_all_doors()

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "request": request,
            "users": users,
            "rentals": rentals,
            "slots": slots,
            "events": events,
            "suspicious_events": suspicious_events,
            "doors": doors,
        },
    )


@app.post("/admin/open-slot")
def admin_open_slot(slot_number: int = Form(...), db: Session = Depends(get_db)):
    slot = db.query(Slot).filter(Slot.slot_number == slot_number).first()
    if slot:
        
# ===== 💳 ОПЛАТА ПЕРЕД ВЫДАЧЕЙ =====

    

        log_event(
            db,
            "admin_open_slot",
            f"Администратор открыл слот {slot.slot_number}.",
            slot_number=slot.slot_number,
        )
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/reset-slots")
def admin_reset_slots(db: Session = Depends(get_db)):
    slots = db.query(Slot).order_by(Slot.slot_number).all()

    for slot in slots:
        if slot.slot_number in [1, 2, 3]:
            slot.status = "available"
        elif slot.slot_number == 4:
            slot.status = "empty"

    rentals = db.query(Rental).filter(Rental.status.in_(["issuing", "active", "returning"])).all()
    for rental in rentals:
        rental.status = "cancelled"
        rental.end_time = now_utc()

    db.commit()

    log_event(
        db,
        "admin_reset_slots",
        "Администратор сбросил слоты и активные аренды.",
    )

    return RedirectResponse(url="/admin", status_code=303)
from fastapi.responses import FileResponse

@app.get("/download-site")
def download_site():
    return FileResponse("/home/pi/iibox_public_site/index.html")


@app.post("/cloudpayments/pay-notification")
async def cloudpayments_pay_notification(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    print("=== CLOUDPAYMENTS PAY NOTIFICATION START ===")
    print(payload)

    account_id = str(payload.get("AccountId", "")).strip()
    token = payload.get("Token")
    transaction_id = payload.get("TransactionId")
    status = payload.get("Status")
    amount = payload.get("Amount")
    invoice_id = payload.get("InvoiceId")

    user = None
    if account_id:
        user = db.query(User).filter(User.phone == account_id).first()

    if user and token:
        user.payment_token = token
        db.commit()
        print("TOKEN SAVED FOR USER:", user.phone)
        log_event(
            db,
            "payment_token_saved",
            f"Токен сохранён через notification. TransactionId={transaction_id}, Status={status}, Amount={amount}, InvoiceId={invoice_id}",
            user_phone=user.phone,
        )
    elif user:
        print("USER FOUND, BUT TOKEN IS EMPTY")
        log_event(
            db,
            "payment_notification_no_token",
            f"Notification пришёл без токена. TransactionId={transaction_id}, Status={status}, Amount={amount}, InvoiceId={invoice_id}",
            user_phone=user.phone,
        )
    else:
        print("USER NOT FOUND FOR ACCOUNT_ID:", account_id)
        log_event(
            db,
            "payment_notification_user_not_found",
            f"Не найден пользователь для AccountId={account_id}. TransactionId={transaction_id}, Status={status}, Amount={amount}, InvoiceId={invoice_id}",
            user_phone=account_id or None,
        )

    print("=== CLOUDPAYMENTS PAY NOTIFICATION END ===")
    return {"code": 0}


# ===== DEBUG USER =====
@app.get("/debug-user")
def debug_user(phone: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == phone).first()
    
    if not user:
        return {"error": "user not found"}

    return {
        "phone": user.phone,
        "token": user.payment_token,
        "last4": user.card_last_four,
        "card_type": user.card_type
    }




# ===== TAKE BY TOKEN =====
@app.post("/take-by-token")
def take_by_token(phone: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == phone).first()

    if not user:
        return {"error": "user not found"}

    if not user.payment_token:
        return {"error": "no payment token"}

    from app.cloudpayments_api import charge_by_token

    result = charge_by_token(
        token=user.payment_token,
        amount=100,
        invoice_id="IIBOX-TOKEN",
        account_id=user.phone
    )

    return {
        "status": "charged",
        "cp_response": result
    }

# ===== END TAKE BY TOKEN =====
