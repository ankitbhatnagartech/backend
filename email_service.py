
import os
import logging
import asyncio
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

class EmailService:
    # SendGrid V3 API Endpoint
    SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
    
    # SENDER_EMAIL and SENDGRID_API_KEY will be loaded lazily in the method
    # to ensure environment variables are loaded by main.py first.

    @classmethod
    async def send_contact_notification(cls, submission: dict):
        """
        Send email notification for new contact submission using SendGrid API.
        """
        try:
            # Load credentials at runtime to respect python-dotenv loading in main.py
            sender_email = os.getenv("EMAIL_USER", "archcostestimator@gmail.com")
            api_key = os.getenv("SENDGRID_API_KEY")

            if not api_key:
                logger.error("❌ SENDGRID_API_KEY is missing. Cannot send email.")
                return False

            # Construct the email payload specifically for SendGrid API
            # Docs: https://docs.sendgrid.com/api-reference/mail-send/mail-send
            
            subject = f"New Contact Request: {submission.get('subject')}"
            
            # Plain text content
            text_content = f"""
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

            # HTML content (optional, but good for reliable formatting)
            html_content = f"""
            <h3>New Contact Request Received</h3>
            <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px;">
                <p><strong>Name:</strong> {submission.get('name')}</p>
                <p><strong>Email:</strong> {submission.get('email')}</p>
                <p><strong>Subject:</strong> {submission.get('subject')}</p>
                <p><strong>Time:</strong> {datetime.utcnow().isoformat()}</p>
            </div>
            <div style="margin-top: 20px; padding: 15px; border-left: 4px solid #007bff;">
                <p>{submission.get('message')}</p>
            </div>
            """

            payload = {
                "personalizations": [
                    {
                        "to": [
                            {"email": sender_email} # Send to self/admin
                        ],
                        "subject": subject
                    }
                ],
                "from": {
                    "email": sender_email,
                    "name": "ArchCost Estimator"
                },
                "reply_to": {
                    "email": submission.get('email'),
                    "name": submission.get('name')
                },
                "content": [
                    {
                        "type": "text/plain",
                        "value": text_content
                    },
                    {
                        "type": "text/html",
                        "value": html_content
                    }
                ]
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            logger.info(f"Sending email via SendGrid API to {sender_email}...")
            
            # Use httpx for async HTTP request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    cls.SENDGRID_API_URL, 
                    json=payload, 
                    headers=headers, 
                    timeout=10.0
                )
                
                if response.status_code in (200, 201, 202):
                    logger.info("✅ Email sent successfully via SendGrid API")
                    return True
                else:
                    logger.error(f"❌ Failed to send email. Status: {response.status_code}, Body: {response.text}")
                    return False

        except Exception as e:
            logger.error(f"❌ Error sending email via SendGrid: {e}", exc_info=True)
            return False
