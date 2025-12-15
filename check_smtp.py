import smtplib
import sys
import os

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def check_connectivity():
    print(f"Testing connectivity to {SMTP_SERVER}:{SMTP_PORT}...")
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
        print("✅ Connection successful!")
        print("Starting TLS...")
        server.starttls()
        print("✅ TLS started successfully!")
        server.quit()
        return True
    except smtplib.SMTPConnectError:
        print("❌ Failed to connect to SMTP server.")
    except Exception as e:
        print(f"❌ Error occurred: {e}")
    return False

if __name__ == "__main__":
    check_connectivity()
