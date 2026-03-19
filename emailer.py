import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


def send_email(excel_path: str, delivery_date: str, config: dict) -> None:
    """Send the Excel file as an email attachment via Gmail SMTP."""
    email_cfg = config["email"]
    dt = datetime.strptime(delivery_date, "%Y-%m-%d")
    date_display = dt.strftime("%d/%m")

    subject = f"Bosh Belfast {date_display}"

    msg = EmailMessage()
    msg["From"] = email_cfg["sender"]
    msg["To"] = ", ".join(email_cfg["recipients"])
    msg["Subject"] = subject
    msg.set_content(email_cfg["body"].format(date=date_display))

    # Attach Excel file
    filename = os.path.basename(excel_path)
    with open(excel_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )

    logger.info("Sending email to %s with subject: %s", email_cfg["recipients"], subject)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(email_cfg["sender"], email_cfg["app_password"])
        server.send_message(msg)

    logger.info("Email sent successfully")
