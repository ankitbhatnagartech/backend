
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

class EmailService:
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    # Hardcoded fallback for now as per user request, but should use env var in prod
    SENDER_EMAIL = os.getenv("EMAIL_USER", "archcostestimator@gmail.com")
    SENDER_PASSWORD = os.getenv("EMAIL_PASSWORD", "qthy dtbn zeoy lrot")

    @classmethod
    async def send_contact_notification(cls, submission: dict):
        """
        Send email notification for new contact submission.
        Runs in a separate thread to avoid blocking the event loop.
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, cls._send_email_sync, submission)
        except Exception as e:
            logger.error(f"Failed to send email async: {e}")

    @classmethod
    def _send_email_sync(cls, submission: dict):
        try:
            msg = MIMEMultipart()
            msg['From'] = cls.SENDER_EMAIL
            msg['To'] = cls.SENDER_EMAIL  # Send to self/admin
            msg['Subject'] = f"New Contact Request: {submission.get('subject')}"

            body = f"""
            New Contact Request Received
            ---------------------------
            Name: {submission.get('name')}
            Email: {submission.get('email')}
            Subject: {submission.get('subject')}
            Time: {datetime.utcnow().isoformat()}

            Message:
            ---------------------------
            {submission.get('message')}
            """
            
            msg.attach(MIMEText(body, 'plain'))

            logger.info(f"Connecting to SMTP server {cls.SMTP_SERVER}...")
            server = smtplib.SMTP(cls.SMTP_SERVER, cls.SMTP_PORT)
            server.starttls()
            server.login(cls.SENDER_EMAIL, cls.SENDER_PASSWORD)
            text = msg.as_string()
            server.sendmail(cls.SENDER_EMAIL, cls.SENDER_EMAIL, text)
            server.quit()
            logger.info(f"✅ Email sent successfully to {cls.SENDER_EMAIL}")
            return True
        except Exception as e:
            logger.error(f"❌ Error sending email: {e}")
            return False
