#User management schema
from pydantic import BaseModel, Field, field_validator

# The cap lives in auth.security, next to the hasher that enforces it. This
# copy existed as a separate literal until now, which is how two of them end
# up disagreeing. Kept here as a validator so an over-long password is a 422
# at the API boundary rather than an exception from deep in the hasher.
from app.auth.security import check_password_bytes as _check_password_bytes


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    # max_length stays above the byte cap so the byte check, not the
    # character count, is what the user is told about.
    password: str = Field(min_length=8, max_length=128)
    role_id: int

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        return _check_password_bytes(value)


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role_id: int | None = None

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str | None) -> str | None:
        return _check_password_bytes(value)


class UserResponse(BaseModel):
    id: int
    username: str
    role_id: int
    role_name: str
    is_active: bool
