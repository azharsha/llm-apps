import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

DEFAULT_PERIOD = "6mo"
DEFAULT_INTERVAL = "1d"

MAX_AGENT_ITERATIONS = 20
