#!/usr/bin/env bash
# ==============================================================================
# Focusloop Studio — macOS & Linux Portable Runner
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "⚡ Starting Focusloop Studio..."

# 1. Locate Python 3
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Error: Python 3 is not installed or not in your PATH."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "   👉 Install via Homebrew: brew install python"
    else
        echo "   👉 Install via package manager: sudo apt install python3 python3-venv python3-pip"
    fi
    exit 1
fi

# 2. Check for FFmpeg
if ! command -v ffmpeg &>/dev/null && [ ! -f "$SCRIPT_DIR/bin/ffmpeg" ]; then
    echo "⚠️  Notice: FFmpeg not detected in PATH or bin/ directory."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "   👉 Install via Homebrew for hardware acceleration: brew install ffmpeg"
    fi
fi

# 3. Initialize or activate local virtual environment
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating local virtual environment in .venv..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# 4. Install / verify dependencies
if [ ! -f "$VENV_DIR/.installed" ]; then
    echo "📥 Installing required studio dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    if [[ "$OSTYPE" == "darwin"* ]]; then
        pip install "pywebview[cocoa]" || true
    fi
    touch "$VENV_DIR/.installed"
fi

# 5. Launch Focusloop Studio Desktop App
echo "🚀 Launching Focusloop Studio UI..."
exec python -m src.gui.app_window