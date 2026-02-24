import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_NAME = "claude-sonnet-4-6"

KERNEL_PATH = os.environ.get("KERNEL_PATH", "")  # path to your kernel source tree
CHROMA_DIR = "data/chroma"
COLLECTION_NAME = "linux_functions"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
LAST_COMMIT_FILE = "data/last_commit.txt"

# Kernel subdirectories to index. Edit and run `python indexer.py --full` to apply.
SUBSYSTEMS = [
    "kernel/sched",
]

MAX_BODY_SNIPPET_LINES = 40
