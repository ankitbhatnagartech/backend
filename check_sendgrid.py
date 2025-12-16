
import os
import asyncio
import httpx
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Credentials from env (SECURITY: Do not hardcode keys)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDER_EMAIL = os.getenv("EMAIL_USER", "archcostestimator@gmail.com")
API_URL = "https://api.sendgrid.com/v3/mail/send"

async def test_sendgrid():
    print(f"Testing SendGrid API...")
    print(f"Sender: {SENDER_EMAIL}")
    print(f"Key Prefix: {SENDGRID_API_KEY[:4]}...")

    payload = {
        "personalizations": [
            {
                "to": [{"email": SENDER_EMAIL}],
                "subject": "Test Email from Check Script"
            }
        ],
        "from": {
            "email": SENDER_EMAIL,
            "name": "ArchCost Test"
        },
        "content": [
            {
                "type": "text/plain",
                "value": "If you see this, SendGrid is working!"
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(API_URL, json=payload, headers=headers)
            print(f"Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")
            
            if response.status_code in (200, 201, 202):
                print("✅ Email sent successfully!")
            else:
                print("❌ Failed to verify.")
        except Exception as e:
            print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_sendgrid())
