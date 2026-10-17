#Authentication specific schema only
from pydantic import BaseModel, field_validator

# The cap itself lives in auth.security, next to the hasher that enforces it.
# Repeating the number here is how the two drifted apart once already.
from app.auth.security import check_password_bytes as _check_password_bytes


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        return _check_password_bytes(value)


class ChangePasswordRequest(BaseModel):
    """Self-service password change from the Topbar account menu.

    The current password proves identity; new + confirm must match so
    the server can reject typos before anything is written.
    """

    current_password: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_length(cls, value: str) -> str:
        return _check_password_bytes(value)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, confirm, info):
        new = info.data.get("new_password")
        if new is not None and confirm != new:
            raise ValueError("New passwords do not match")
        return confirm
