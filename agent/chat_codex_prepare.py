"""Cancellable subprocess boundary for managed Codex setup.

The child may persist a signed policy checkpoint or fully verified binaries
before cancellation. Such completed state remains valid; it does not authorize
login or launch. Partially written files are never selected for execution.
"""
import json
import os
import re
import subprocess
import tempfile
import time


class PreparationCancelled(Exception):
    pass


def run_preparation(argv, *, cancelled, timeout=120, poll_interval=0.05, env=None):
    if os.name != 'posix' or not argv or not callable(cancelled):
        raise ValueError('prepare-unavailable')
    if cancelled():
        raise PreparationCancelled()
    from .chat_process_supervisor import MacOSProcessSupervisor
    supervisor = MacOSProcessSupervisor()
    with tempfile.TemporaryFile(mode='w+b') as output:
        proc = supervisor.spawn(argv, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.DEVNULL, env=env)
        deadline = time.monotonic() + timeout
        finished = False
        try:
            while True:
                if cancelled():
                    supervisor.terminate_tree(proc)
                    finished = True
                    raise PreparationCancelled()
                if os.fstat(output.fileno()).st_size > 4096:
                    raise ValueError('prepare-output-invalid')
                if supervisor._observe_exit(proc, 0) is not None:
                    status, _tree_complete = supervisor.finish(proc, 0)
                    finished = True
                    if cancelled():
                        raise PreparationCancelled()
                    if status != 0:
                        raise ValueError('prepare-failed')
                    break
                if time.monotonic() >= deadline:
                    raise ValueError('prepare-timeout')
                time.sleep(poll_interval)
            output.seek(0)
            try:
                value = json.loads(output.read(4097).decode('utf-8'))
            except (ValueError, UnicodeError):
                raise ValueError('prepare-output-invalid') from None
            if (not isinstance(value, dict) or set(value) != {'path', 'version'}
                    or not isinstance(value['path'], str) or not os.path.isabs(value['path'])
                    or len(value['path']) > 2048 or not isinstance(value['version'], str)
                    or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value['version'])):
                raise ValueError('prepare-output-invalid')
            return value
        finally:
            if not finished:
                supervisor.terminate_tree(proc)
