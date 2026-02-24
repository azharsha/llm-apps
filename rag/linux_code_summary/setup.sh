#!/usr/bin/env bash
set -euo pipefail

KERNEL_DIR="kernel"
KERNEL_REPO="https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"

echo "=== Linux Kernel Code Summary — Setup ==="

# 1. Clone the kernel (shallow, main branch only) if not already present
if [ ! -d "$KERNEL_DIR/.git" ]; then
    echo "Cloning Linux kernel (shallow) — this may take a few minutes ..."
    git clone --depth=1 --single-branch --branch master "$KERNEL_REPO" "$KERNEL_DIR"
else
    echo "Kernel repo already present at ./$KERNEL_DIR"
fi

# 2. Record the current HEAD as the baseline for incremental sync
mkdir -p data
git -C "$KERNEL_DIR" rev-parse HEAD > data/last_commit.txt
echo "Baseline commit recorded: $(cat data/last_commit.txt)"

# 3. Set up Python virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment ..."
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "Dependencies installed."

# 4. Copy .env if not present
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env — please set ANTHROPIC_API_KEY inside it."
fi

# 5. Run the initial index
echo "Starting initial index (this can take 10–20 minutes) ..."
python indexer.py --full

echo ""
echo "Setup complete! Start the server with:"
echo "  source .venv/bin/activate"
echo "  uvicorn app:app --reload --port 8000"
