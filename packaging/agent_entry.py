"""Frozen CLI entry. The only desktop-specific protocol is process supervision."""
from __future__ import annotations

import _thread
import json
import os
import sys
import threading


def _stop_from_parent():
    # EOF means the owning desktop has gone away. No persisted state is removed.
    try:
        line = sys.stdin.readline(256)
        if not line or json.loads(line).get("command") == "stop":
            _thread.interrupt_main()
    except (OSError, ValueError, AttributeError):
        return


def main(argv=None):
    import agent
    from agent import cli
    from _desktop_build import APP_VERSION
    args = list(sys.argv[1:] if argv is None else argv)
    # Windows pipes default to the ANSI code page (e.g. cp1252) and fail on Korean text.
    # The desktop shell decodes child output as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", line_buffering=True)
    if args == ["--desktop-info"]:
        print(json.dumps({"app_version": APP_VERSION, "agent_version": agent.AGENT_VERSION, "protocol": 1}))
        return 0
    # Never compete with connect --token-stdin for input.
    if os.environ.get("MYCRM_DESKTOP_CONTROL") == "1":
        parsed = cli._parser().parse_args(args)
        if parsed.cmd == "serve":
            threading.Thread(target=_stop_from_parent, daemon=True).start()
    return cli.main(args)


if __name__ == "__main__":
    sys.exit(main())
