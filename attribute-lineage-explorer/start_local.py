#!/usr/bin/env python3
"""Start AISL Explorer only on this computer, using Python's standard library.

Usage (Windows): py -3 start_local.py
Usage (macOS/Linux): python3 start_local.py
Stop: Ctrl+C in the same terminal.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

ROOT = Path(__file__).resolve().parent
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'none'; img-src 'self' data:; font-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)


class LocalHandler(SimpleHTTPRequestHandler):
    # .mjs is not registered consistently on all Windows/Python versions.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.mjs': 'text/javascript'}

    def end_headers(self) -> None:
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description='Run AISL Explorer locally; listens only on 127.0.0.1')
    parser.add_argument('--port', type=int, default=8080, help='Local port, default 8080; 0 chooses a free port')
    parser.add_argument('--no-open', action='store_true', help='Do not open a browser tab automatically')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port must be in 0..65535')
    handler = partial(LocalHandler, directory=str(ROOT))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as exc:
        parser.exit(1, f'Cannot start local server on port {args.port}: {exc}\nTry --port 0\n')
    with server:
        url = f'http://127.0.0.1:{server.server_port}/'
        print(f'AISL Explorer: {url}', flush=True)
        print('Only this computer can access the server. Stop with Ctrl+C.', flush=True)
        if not args.no_open:
            webbrowser.open_new_tab(url)
        try:
            server.serve_forever(poll_interval=0.15)
        except KeyboardInterrupt:
            print('\nServer stopped.', flush=True)


if __name__ == '__main__':
    main()
