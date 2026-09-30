import smtplib
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

def send_email(to_address, subject, body, is_html=False):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if is_html else "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)


def send_html_email_with_image(to_address, subject, html_body, image_bytes, image_cid):
    # A separate function rather than extending send_email, so the existing
    # signature every connector already calls stays untouched.
    msg = MIMEMultipart("related")
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_address
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    image = MIMEImage(image_bytes)
    image.add_header("Content-ID", f"<{image_cid}>")
    image.add_header("Content-Disposition", "inline", filename=f"{image_cid}.png")
    msg.attach(image)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)

if __name__ == "__main__":
    send_email(
        to_address=EMAIL_ADDRESS,
        subject="Test email from job scraper",
        body="If you're reading this, it worked!"
    )
    print("Email sent")