from pydantic import BaseModel, SecretStr, Field
from typing import Optional, Literal


class Add_User(BaseModel):
    """Register with a mobile number and/or email. `user_name` is kept for older clients (email)."""
    user_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    first_name: str = Field(..., min_length=1, max_length=30)
    last_name: str = Field("", max_length=30)
    password: SecretStr
    role: Optional[Literal["farmer", "vendor"]] = None
    role_id: Optional[int] = None
    state: Optional[int] = None
    district: Optional[int] = None
    preferred_language: Literal["en", "te"] = "en"
    created_by: Optional[int] = None  # ignored


class VerifyUserOtp(BaseModel):
    user_name: str  # the email or mobile number the code was sent to
    otp: SecretStr


class ResendOtpSchema(BaseModel):
    identifier: str


class UpdateProfileSchema(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    state: Optional[int] = None
    district: Optional[int] = None
    preferred_language: Optional[Literal["en", "te"]] = None


class ChangeContactSchema(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None


class VerifyContactSchema(BaseModel):
    identifier: str
    otp: SecretStr


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class LogoutSchema(BaseModel):
    all_devices: bool = False


class MfaLoginSchema(BaseModel):
    mfa_token: str
    code: str = Field(..., min_length=6, max_length=6)


class MfaCodeSchema(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class PasswordResetRequestSchema(BaseModel):
    identifier: str


class PasswordResetConfirmSchema(BaseModel):
    identifier: str
    otp: SecretStr
    new_password: SecretStr


class ChangePasswordSchema(BaseModel):
    current_password: SecretStr
    new_password: SecretStr


class PasswordConfirmSchema(BaseModel):
    password: SecretStr
    reason: Optional[str] = Field(None, max_length=500)


class AppealSchema(BaseModel):
    identifier: str
    password: SecretStr
    reason: str = Field(..., min_length=10, max_length=1000)
