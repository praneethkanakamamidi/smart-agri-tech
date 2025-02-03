import os
import smtplib
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.helpers.settings_config import SMTPSettings  # Load settings from configuration
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class SmtpService:
    """Service for handling email-related functionalities like sending alerts and generating OTPs."""

    def __init__(self):
        """Initializes SMTP configuration using SMTPSettings class."""
        self.smtp_settings = SMTPSettings()  # Load settings from the SMTPSettings class
        
        # Ensure all required environment variables are available
        if not all([self.smtp_settings.EMAIL_SMTP_SERVER, 
                    self.smtp_settings.EMAIL_SENDER_ADDRESS, 
                    self.smtp_settings.EMAIL_SENDER_PASSWORD]):
            raise ValueError("Missing required environment variables for SMTP configuration.")

    def generate_secure_otp(self, length: int = 6) -> str:
        """
        Generate a secure One-Time Password (OTP) with random letters and digits.

        :param length: Length of the OTP (default is 6 characters).
        :return: Randomly generated OTP as a string.
        """
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def send_email_alert(self, recipient_email: str, subject: str, message: str) -> bool:
        """
        Send an email using SMTP with the provided subject and message content.

        :param recipient_email: Email address of the recipient.
        :param subject: Subject of the email.
        :param message: Body of the email message.
        :return: True if the email was sent successfully, False otherwise.
        """
        try:
            # Set up the MIME structure of the email
            msg = MIMEMultipart()
            msg['From'] = self.smtp_settings.EMAIL_SENDER_ADDRESS
            msg['To'] = recipient_email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))

            # Connect to SMTP server and send the email
            with smtplib.SMTP(self.smtp_settings.EMAIL_SMTP_SERVER, self.smtp_settings.EMAIL_SMTP_PORT) as server:
                server.starttls()  # Secure the connection using TLS
                server.login(self.smtp_settings.EMAIL_SENDER_ADDRESS, self.smtp_settings.EMAIL_SENDER_PASSWORD)
                server.send_message(msg)

            return True
        except smtplib.SMTPException as e:
            print(f"Error sending email: {e}")  # Log the error for debugging
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")  # Catch any other exceptions
            return False
