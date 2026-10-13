from pydantic_settings import BaseSettings


class OAuthSettings(BaseSettings):
    ACCESS_TOKEN: str
    REFRESH_TOKEN: str
    ALGORITHM: str
    ACCESS_EXPIRY: int = 60
    REFRESH_EXPIRY: int = 10080  # 30*24*7

class SMTPSettings(BaseSettings):    
    EMAIL_SENDER_ADDRESS: str
    EMAIL_SENDER_PASSWORD: str
    EMAIL_SMTP_SERVER: str
    EMAIL_SMTP_PORT: int

class RazorPaySettings(BaseSettings):
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str