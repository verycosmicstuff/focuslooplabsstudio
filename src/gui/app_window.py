import sys
import time
import threading
import uvicorn
import webview
from src.config import DEFAULT_PORT, DEFAULT_HOST
from src.api.server import app

def start_server():
    uvicorn.run(app, host=DEFAULT_HOST, port=DEFAULT_PORT, log_level="warning")

def run_app():
    # Set Windows AppUserModelID for taskbar icon grouping
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("verycosmicstuff.savespace.pro")
    except Exception:
        pass

    # Start API server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait briefly for server startup
    time.sleep(1.0)

    # Launch PyWebView native Windows desktop window
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    window = webview.create_window(
        title="SaveSpace — Ultimate Storage Manager & Transcoder",
        url=url,
        width=1400,
        height=900,
        min_size=(1050, 720),
        background_color="#0b0f19",
        text_select=True
    )
    webview.start(debug=False)

if __name__ == "__main__":
    run_app()
