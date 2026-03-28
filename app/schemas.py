from pydantic import BaseModel


class UserRegister(BaseModel):
    phone: str
    pin: str


class UserLogin(BaseModel):
    phone: str
    pin: str
