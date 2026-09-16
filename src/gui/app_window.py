import sys
import time
import threading
import uvicorn
import webview
from src.config import DEFAULT_PORT, DEFAULT_HOST
from src.api.server import app

from pathlib import Path

def start_server():
    uvicorn.run(app, host=DEFAULT_HOST, port=DEFAULT_PORT, log_level="warning")

def run_app():
    # Set Windows AppUserModelID for taskbar icon grouping
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("focuslooplabs.studio.pro")
    except Exception:
        pass

    # Start API server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait briefly for server startup
    time.sleep(1.0)

    # Resolve application icon path for native Windows window & taskbar
    base_dir = Path(__file__).resolve().parent.parent.parent
    icon_path = base_dir / "ui" / "icons" / "app_icon.ico"
    if not icon_path.exists():
        icon_path = base_dir / "FocusloopLabs.ico"

    # Launch PyWebView native Windows desktop window
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    window = webview.create_window(
        title="Focusloop Studio — Studio Assistant & Media Manager",
        url=url,
        width=1400,
        height=900,
        min_size=(1050, 720),
        background_color="#0b0f19",
        text_select=True
    )
    webview.start(icon=str(icon_path) if icon_path.exists() else None, debug=False)

if __name__ == "__main__":
    run_app()
