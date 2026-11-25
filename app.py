"""Lightweight launcher for Resume Copilot.

Supports two ways to run on any laptop:
1. Direct lightweight mode (recommended): `python app.py` (or `uvicorn api.app:app`)
2. Streamlit bridge mode: `streamlit run app.py` (embeds the FastAPI Web UI seamlessly)
"""

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from api.app import create_app

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_API_URL = os.getenv("RESUME_COPILOT_API_URL", "")


def _find_free_port(preferred: int = 8000) -> int:
    for port in (preferred, 8001, 8080, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Could not find a free local port for Resume Copilot.")


def start_backend_thread(preferred_port: int = 8000) -> str:
    """Start FastAPI + static Web UI in a background thread and wait for /health."""
    if DEFAULT_API_URL:
        try:
            if httpx.get(f"{DEFAULT_API_URL}/health", timeout=1.5).status_code == 200:
                return DEFAULT_API_URL
        except httpx.HTTPError:
            pass

    port = _find_free_port(preferred_port)
    api_url = f"http://127.0.0.1:{port}"
    app = create_app(runs_dir=ROOT_DIR / "runs")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    threading.Thread(target=server.run, daemon=True).start()

    for _ in range(30):
        try:
            if httpx.get(f"{api_url}/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.15)
    return api_url


def _run_streamlit_bridge() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Resume Copilot",
        page_icon="✦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    @st.cache_resource
    def _ensure_server() -> str:
        return start_backend_thread(8000)

    ui_url = _ensure_server()

    st.markdown(
        """
        <style>
          #MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
          .block-container { padding: 0 !important; max-width: 100% !important; }
          iframe { border: none !important; width: 100% !important; height: 96vh !important; }
          .rc-launch-strip {
            display: flex; align-items: center; justify-content: space-between;
            padding: 6px 16px; background: #0f172a; color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 12px;
          }
          .rc-launch-strip a {
            color: #93c5fd; text-decoration: none; font-weight: 600;
            padding: 3px 10px; border-radius: 999px; border: 1px solid #334155;
          }
          .rc-launch-strip a:hover { background: #1e293b; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="rc-launch-strip">'
        f'<span>Resume Copilot Web Studio running via local server at <code>{ui_url}</code></span>'
        f'<a href="{ui_url}" target="_blank" rel="noopener">Open Full-Screen Tab ↗</a>'
        f"</div>",
        unsafe_allow_html=True,
    )
    if hasattr(st, "iframe"):
        st.iframe(ui_url, height=900)
    else:
        st.components.v1.iframe(ui_url, height=900, scrolling=True)


def _running_inside_streamlit() -> bool:
    try:
        import streamlit.runtime as rt

        return rt.exists()
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Resume Copilot lightweight web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--no-browser", action="store_true")
    args, _ = parser.parse_known_args()

    port = _find_free_port(args.port)
    url = f"http://{args.host}:{port}"
    print(f"\n  Resume Copilot is running at: {url}\n  Press Ctrl+C to stop.\n", flush=True)

    if not args.no_browser:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()

    app = create_app(runs_dir=ROOT_DIR / "runs")
    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if _running_inside_streamlit():
    _run_streamlit_bridge()
elif __name__ == "__main__":
    main()
