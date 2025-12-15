import smtplib
import sys
import os

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def check_connectivity():
    print(f"Testing connectivity to {SMTP_SERVER}:{587} (TLS)...")
    try:
        server = smtplib.SMTP(SMTP_SERVER, 587, timeout=10)
        print("✅ Connection successful to port 587!")
        server.quit()
    except Exception as e:
        print(f"❌ Failed to connect to port 587: {e}")

    print(f"\nTesting connectivity to {SMTP_SERVER}:{465} (SSL)...")
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=10)
        print("✅ Connection successful to port 465!")
        server.quit()
    except Exception as e:
        print(f"❌ Failed to connect to port 465: {e}")

if __name__ == "__main__":
    check_connectivity()
