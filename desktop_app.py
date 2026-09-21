from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path


APP_NAME = "Paper Orbit"
from literature_radar.paths import workspace_root, prepare_workspace, acquire_workspace_lock, startup_backup, migrate_config_credentials


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = workspace_root()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-main":
        run_cli_main(sys.argv[2:])
        return

    args = parse_args()
    try:
        acquire_workspace_lock()
        prepare_workspace()
        migrate_config_credentials()
        startup_backup()
    except (RuntimeError,OSError,ValueError) as exc:
        if args.no_window:
            print('Workspace startup failed: '+type(exc).__name__,flush=True)
            raise SystemExit(2)
        show_webview_error(str(exc))
        return
    ensure_workspace_dirs()
    os.chdir(ROOT)

    host = args.host
    port = pick_port(host, args.port)
    server = start_server(host, port)
    url = f"http://{host}:{port}" + ("/discover" if args.page == "discover" else "/")

    print(f"{APP_NAME}: {url}", flush=True)
    if args.open_browser and not args.no_browser:
        webbrowser.open(url)

    if args.no_window:
        run_console(server, url)
    else:
        run_window(server, url)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the desktop launcher for the literature workspace.")
    parser.add_argument("--page", choices=("discover", "library"), default="discover", help="Choose the initial workspace page.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open-browser", action="store_true", help="Open the local workspace in the default browser as well.")
    parser.add_argument("--no-browser", action="store_true", help="Legacy option; the desktop window does not open a browser by default.")
    parser.add_argument("--no-window", action="store_true", help="Run with console status only.")
    return parser.parse_args()


def run_cli_main(argv: list[str]) -> None:
    os.environ.setdefault("LITERATURE_RADAR_ROOT", str(ROOT))
    os.chdir(ROOT)
    sys.argv = ["main.py", *argv]
    import main as cli_main

    cli_main.main()


def ensure_workspace_dirs() -> None:
    for name in ("data", "logs", "reports"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        if can_bind(host, port):
            return port
    raise RuntimeError(f"No free port found from {preferred} to {preferred + 49}.")


def can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def start_server(host: str, port: int) -> ThreadingHTTPServer:
    import web_app

    from literature_radar.security import require_loopback
    require_loopback(host)
    server = ThreadingHTTPServer((host, port), web_app.LiteratureHandler)
    thread = threading.Thread(target=server.serve_forever, name="literature-web", daemon=True)
    thread.start()
    return server


def run_console(server: ThreadingHTTPServer, url: str) -> None:
    print("Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server(server)
        print(f"Stopped {url}", flush=True)


def run_window(server: ThreadingHTTPServer, url: str) -> None:
    try:
        import webview
    except ImportError:
        show_webview_error()
        stop_server(server)
        return

    try:
        webview.create_window(
            APP_NAME,
            url,
            width=1440,
            height=940,
            min_size=(1024, 700),
            resizable=True,
            text_select=True,
            background_color="#f4f7f8",
            confirm_close=True,
        )
        webview.start(gui="edgechromium")
    except Exception as exc:
        print(f"Could not start the embedded desktop window: {exc}", flush=True)
        show_webview_error(str(exc))
    finally:
        stop_server(server)


def show_webview_error(detail: str = "") -> None:
    """Show a useful native error when the embedded browser runtime is unavailable."""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        return

    root = tk.Tk()
    root.withdraw()
    message = (
        "The embedded desktop window could not start.\n\n"
        "Run start_desktop_app.bat once to install its required components, then try again."
    )
    if detail:
        message = f"{message}\n\nDetails: {detail}"
    messagebox.showerror(APP_NAME, message)
    root.destroy()


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        webbrowser.open(path.as_uri())


def stop_server(server: ThreadingHTTPServer) -> None:
    # Background workflow threads exit with this process; persisted leases detect interruption.
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    main()
