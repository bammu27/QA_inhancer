"""
Unit 7 — Email Dispatch
Sends the approved Markdown report as a rendered HTML email (with a
plain-text fallback) and attaches the raw .md file verbatim.
Never raises — all failure paths return {"status": "failed", "error": "..."}.
"""

import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

import markdown as md

import config

EMAIL_CSS = """
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; color: #222; line-height: 1.5; }
  h1 { font-size: 20px; }
  h3 { font-size: 16px; margin-top: 0; }
  table { border-collapse: collapse; margin: 12px 0; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
  blockquote { border-left: 4px solid #f0ad4e; margin: 10px 0; padding: 6px 12px; background: #fff8ec; color: #555; }
  hr { border: none; border-top: 1px solid #ddd; margin: 16px 0; }
  code { background: #f2f2f2; padding: 1px 5px; border-radius: 3px; }
</style>
"""


def send_report(markdown_text: str, developer_email: str) -> dict:
    """
    Args:
        markdown_text: the exact string to send — must be
                   st.session_state["final_markdown"], unmodified,
                   verbatim. Used, untouched, in both the plain-text part
                   and the .md attachment; rendered (not rewritten) into
                   HTML for the third part.
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

    # Render HTML from the exact same string — no second formatting path.
    html_fragment = md.markdown(markdown_text, extensions=["tables", "fenced_code"])
    full_html = f"<html><head>{EMAIL_CSS}</head><body>{html_fragment}</body></html>"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = "Defect Report — Auto-Generated"
    msg["From"] = config.SMTP_FROM_EMAIL or config.SMTP_USERNAME
    msg["To"] = developer_email

    # Plain text + HTML as alternative views of the same body.
    body = MIMEMultipart("alternative")
    body.attach(MIMEText(markdown_text, "plain", "utf-8"))
    body.attach(MIMEText(full_html, "html", "utf-8"))
    msg.attach(body)

    # Raw .md file attached verbatim.
    attachment = MIMEBase("text", "markdown")
    attachment.set_payload(markdown_text.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition", 'attachment; filename="defect_report.md"'
    )
    msg.attach(attachment)

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