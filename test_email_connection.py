
import smtplib
import os

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "archcostestimator@gmail.com"
SENDER_PASSWORD = "qthy dtbn zeoy lrot"

print("--- Starting SMTP Connection Test ---")
try:
    print(f"1. Connecting to {SMTP_SERVER}:{SMTP_PORT}...")
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.ehlo()
    
    print("2. Starting TLS...")
    server.starttls()
    server.ehlo()
    
    print(f"3. Attempting login as {SENDER_EMAIL}...")
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    
    print("✅ Login SUCCESSFUL!")
    server.quit()
except Exception as e:
    print(f"❌ Login FAILED: {e}")
    # Print detailed type for easier debugging
    print(f"Error Type: {type(e).__name__}")
