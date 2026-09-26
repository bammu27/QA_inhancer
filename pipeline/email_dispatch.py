"""
Unit 7 — Email Dispatch
Sends the approved Markdown report verbatim via SMTP.
Never raises — all failure paths return {"status": "failed", "error": "..."}.
"""

import smtplib
from email.mime.text import MIMEText

import config


def send_report(markdown: str, developer_email: str) -> dict:
    """
    Args:
        markdown: the exact string to send as the email body — must be
                   st.session_state["final_markdown"], unmodified,
                   verbatim. No re-formatting, no HTML conversion, no
                   truncation.
        developer_email: recipient address, already validated as
                   non-empty by the caller (app.py) before this is called.

    Returns:
        {"status": "sent"} on success.
        {"status": "failed", "error": "<human-readable message>"} on any
        failure — SMTP connection error, auth failure, invalid recipient,
        etc. This function NEVER raises — every failure path is caught
        internally and returned as a "failed" dict, since the caller
        (app.py) needs a result to show a toast either way, not an
        exception to catch.
    """
    if not config.SMTP_HOST or not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        return {
            "status": "failed",
            "error": (
                "SMTP is not configured. Check SMTP_HOST, SMTP_USERNAME, "
                "and SMTP_PASSWORD in .env."
            ),
        }

    msg = MIMEText(markdown, "plain", "utf-8")
    msg["Subject"] = "Defect Report — Auto-Generated"
    msg["From"] = config.SMTP_FROM_EMAIL or config.SMTP_USERNAME
    msg["To"] = developer_email

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            if config.SMTP_USE_TLS:
                server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(msg["From"], [developer_email], msg.as_string())
        return {"status": "sent"}
    except smtplib.SMTPAuthenticationError as e:
        return {"status": "failed", "error": f"SMTP authentication failed: {e}"}
    except smtplib.SMTPException as e:
        return {"status": "failed", "error": f"SMTP error: {e}"}
    except (OSError, TimeoutError) as e:
        return {"status": "failed", "error": f"Could not connect to SMTP server: {e}"}
    except Exception as e:
        return {"status": "failed", "error": f"Unexpected error sending email: {e}"}
