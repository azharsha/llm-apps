import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

PATCHWORK_BASE_URL = "https://patchwork.kernel.org/api"
REQUEST_TIMEOUT = 30

MAX_AGENT_ITERATIONS = 40
DEFAULT_LIMIT = 15
DEFAULT_DAYS_BACK = 1

# Max diff chars to send to the model per patch (keeps tokens manageable)
MAX_DIFF_CHARS = 8000
