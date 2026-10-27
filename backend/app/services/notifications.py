import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MissingPersonCase, User

logger = logging.getLogger(__name__)


def notify_case_users(db: Session, case: MissingPersonCase, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_sender:
        return
    roles = {role.strip() for role in settings.smtp_recipient_roles.split(",") if role.strip()}
    recipients = db.scalars(select(User).where(
        User.is_active.is_(True),
        ((User.role.in_(roles) & (User.role == "admin")) | (User.id == case.created_by_id)),
    )).all()
    if not recipients:
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_sender
    message["To"] = ", ".join(user.email for user in recipients)
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Email notification failed for case %s", case.id)
