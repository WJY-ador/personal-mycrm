"""Frozen CLI entry. The only desktop-specific protocol is process supervision."""
from __future__ import annotations

import _thread
import json
import os
import ssl
import sys
import threading

try:
    # Imported at top level so PyInstaller's certifi hook bundles cacert.pem.
    import certifi
except ImportError:  # source runs use the system Python's CA store
    certifi = None


def _use_bundled_ca():
    # The frozen OpenSSL looks for CAs at the build machine's path, which users do not have.
    # Respect an explicit SSL_CERT_FILE (e.g. a corporate CA); otherwise use the bundled file.
    if certifi is not None and getattr(sys, "frozen", False) and not os.environ.get("SSL_CERT_FILE"):
        os.environ["SSL_CERT_FILE"] = certifi.where()


def _ca_info():
    # Deterministic, network-free proof of which CA file loads. Never prints the path.
    cafile = os.environ.get("SSL_CERT_FILE", "")
    bundle = getattr(sys, "_MEIPASS", None)
    bundled = bool(bundle and cafile and os.path.realpath(cafile).startswith(os.path.realpath(bundle) + os.sep))
    count = 0
    if cafile and os.path.isfile(cafile):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            context.load_verify_locations(cafile=cafile)
            count = context.cert_store_stats()["x509_ca"]
        except (OSError, ssl.SSLError):  # a broken user-chosen file must not break the version handshake
            count = 0
    return {"ca_bundled": bundled, "ca_count": count}


def _stop_from_parent():
    # EOF means the owning desktop has gone away. No persisted state is removed.
    try:
        line = sys.stdin.readline(256)
        if not line or json.loads(line).get("command") == "stop":
            _thread.interrupt_main()
    except (OSError, ValueError, AttributeError):
        return


def main(argv=None):
    _use_bundled_ca()
    import agent
    from agent import cli
    from _desktop_build import APP_VERSION
    args = list(sys.argv[1:] if argv is None else argv)
    # Windows pipes default to the ANSI code page (e.g. cp1252) and fail on Korean text.
    # The desktop shell decodes child output as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if args == ["--desktop-info"]:
        print(json.dumps({"app_version": APP_VERSION, "agent_version": agent.AGENT_VERSION, "protocol": 1,
                          **_ca_info()}))
        return 0
    # Never compete with connect --token-stdin for input.
    if os.environ.get("MYCRM_DESKTOP_CONTROL") == "1":
        parsed = cli._parser().parse_args(args)
        if parsed.cmd == "serve":
            threading.Thread(target=_stop_from_parent, daemon=True).start()
    return cli.main(args)


if __name__ == "__main__":
    sys.exit(main())
