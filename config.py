import os
from dotenv import load_dotenv

load_dotenv()

TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "templates")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_EXTRACTION = os.getenv("GROQ_MODEL_EXTRACTION", "llama-3.3-70b-versatile")
GROQ_MODEL_REASONING = os.getenv("GROQ_MODEL_REASONING", "llama-3.3-70b-versatile")
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))

# --- External Context Enrichment (Unit 4b) ---
# GITHUB_TOKEN: optional — raises unauthenticated limit from 60 to 5,000 req/h
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
# STACKEXCHANGE_KEY: optional — raises unauthenticated limit from 300 to higher quota
STACKEXCHANGE_KEY = os.getenv("STACKEXCHANGE_KEY", "")
# Set to "false" to disable all external HTTP calls (offline / CI mode)
CONTEXT_ENRICHMENT_ENABLED = os.getenv("CONTEXT_ENRICHMENT_ENABLED", "true").lower() == "true"

# Unit 6/7 — SMTP (email dispatch). No validation at import time:
# missing credentials surface as a send-time error in the UI, not a crash.
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
DEFAULT_DEVELOPER_EMAIL = os.getenv("DEFAULT_DEVELOPER_EMAIL", "")
