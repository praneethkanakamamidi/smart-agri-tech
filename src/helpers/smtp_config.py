import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.helpers.logging_config import get_logger
from src.helpers.settings_config import SMTPSettings  # Load settings from configuration
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = get_logger(__name__)


class SmtpService:
    """Sends email through the configured SMTP server."""

    def __init__(self):
        """Initializes SMTP configuration using SMTPSettings class."""
        self.smtp_settings = SMTPSettings()  # Load settings from the SMTPSettings class

        # Ensure all required environment variables are available
        if not all([self.smtp_settings.EMAIL_SMTP_SERVER,
                    self.smtp_settings.EMAIL_SENDER_ADDRESS,
                    self.smtp_settings.EMAIL_SENDER_PASSWORD]):
            raise ValueError("Missing required environment variables for SMTP configuration.")

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
            logger.error(f"SMTP error sending email: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending email: {e}")
            return False
