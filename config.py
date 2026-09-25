import os
from dotenv import load_dotenv

load_dotenv()

TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "templates")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_EXTRACTION = os.getenv("GROQ_MODEL_EXTRACTION", "llama-3.3-70b-versatile")
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))
