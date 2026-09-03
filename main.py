import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="SaveSpace: Media Storage Manager & Transcoder")
    parser.add_argument("--server", action="store_true", help="Run only the FastAPI background server without opening the desktop window")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind server (default: 8765)")
    args = parser.parse_args()

    if args.server:
        import uvicorn
        from src.api.server import app
        print(f"Starting SaveSpace server on http://127.0.0.1:{args.port}...")
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    else:
        from src.gui.app_window import run_app
        print("Launching SaveSpace Standalone Desktop Application...")
        run_app()

if __name__ == "__main__":
    main()
