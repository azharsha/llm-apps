import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

MAX_AGENT_ITERATIONS = 100
MAX_COMMITS_PER_SESSION = 50
CHECKPATCH_STRICT = True
BUILD_TIMEOUT_SECONDS = 600  # 10 minutes
