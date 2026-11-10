"""Opt-in compatibility probes against a real CLI and a local synthetic model.

Never uses user credentials or data. Passing a probe does not itself issue a
policy or grant authorization; CI must additionally bind evidence to the
tested package, executable, platform and source revision before any issuance.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.server
import json
import os
import platform
import queue
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time

from .chat_codex_app_provider import _build_appserver_argv, _capture_version_output
from .chat_codex_dynamic import AppServerProcess
from .chat_codex_fingerprint import source_fingerprint
from .chat_codex_managed import install_native
from .chat_process_supervisor import MacOSProcessSupervisor

_MARKER = 'MYCRM_SYNTHETIC_PRIVATE_4e2a'
_CALLS = {
    'find': 'text(await tools.mycrm_find({}))',
    'read': 'text(await tools.mycrm_read({}))',
    'write': 'text(await tools.mycrm_write({}))',
    'decide': 'text(await tools.mycrm_decide({}))',
    'fileprobe': 'text(await tools.read_file({path:"synthetic-secret.txt"}))',
    'filecat': 'text(await tools.exec_command({cmd:"cat synthetic-secret.txt"}))',
    'view': 'text(await tools.view_image({path:"synthetic-secret.txt"}))',
    'shell': 'text(await tools.exec_command({cmd:"touch synthetic-probe.txt"}))',
    'patch': 'text(await tools.apply_patch("*** Begin Patch\\n*** Add File: synthetic-probe.txt\\n+synthetic\\n*** End Patch"))',
    'web': 'text(await tools.web__run({search_query:[{q:"synthetic"}]}))',
    'mcp': 'text(await tools.read_mcp_resource({server:"synthetic",uri:"file:///synthetic"}))',
    'goal': 'text(await tools.create_goal({objective:"synthetic"}))',
    'node': 'text(await import("node:fs"))',
}
_ALLOWED = frozenset(('find', 'read', 'write', 'decide'))


def validate_version(actual, expected):
    if (not isinstance(expected, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', expected)
            or actual.strip() != 'codex-cli ' + expected):
        raise ValueError('cli-version-mismatch')


def digest_file(path):
    result = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def digest_package(root):
    """Hash every file and link in the temporary npm installation, not only its wrapper."""
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        raise ValueError('package-unavailable')
    result = hashlib.sha256()
    for current, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        for name in directories + files:
            path = os.path.join(current, name)
            relative = os.path.relpath(path, root).replace(os.sep, '/')
            if os.path.islink(path):
                target = os.path.realpath(path)
                if os.path.commonpath((root, target)) != root:
                    raise ValueError('external-package-link')
                result.update(('link\0' + relative + '\0' + os.readlink(path) + '\n').encode())
            elif os.path.isfile(path):
                result.update(('file\0' + relative + '\0' + digest_file(path) + '\n').encode())
            elif not os.path.isdir(path):
                raise ValueError('unsupported-package-entry')
    return result.hexdigest()


def check_observation(mode, observation):
    if (mode not in _CALLS or observation.get('requests') != 2
            or observation.get('created') is not False or observation.get('exposed') is not False):
        raise ValueError('invalid-probe-observation')
    if mode in _ALLOWED:
        if observation.get('dynamic') != ['mycrm_' + mode] or 'synthetic ok' not in observation.get('outputs', ''):
            raise ValueError('mycrm-tool-unavailable')
    elif (observation.get('dynamic') != [] or 'Script error:' not in observation.get('outputs', '')
          or 'Script failed' not in observation.get('outputs', '')):
        raise ValueError('forbidden-tool-not-rejected')


def run_probe(cli, mode, *, timeout=30):
    if mode not in _CALLS or not os.path.isfile(cli) or not os.access(cli, os.X_OK):
        raise ValueError('invalid-probe-input')
    arrivals, ready = [], threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 1024 * 1024:
                self.send_error(400)
                return
            arrivals.append(json.loads(self.rfile.read(length)))
            if len(arrivals) == 1:
                events = [{'type': 'response.output_item.done', 'item': {
                    'type': 'custom_tool_call', 'call_id': 'synthetic_call', 'name': 'exec',
                    'namespace': 'functions', 'input': _CALLS[mode]}},
                    {'type': 'response.completed', 'response': {'id': 'synthetic_1'}}]
            else:
                events = [{'type': 'response.output_item.done', 'item': {'type': 'message',
                    'id': 'synthetic_answer', 'role': 'assistant', 'content': [
                        {'type': 'output_text', 'text': 'Synthetic done'}]}},
                    {'type': 'response.completed', 'response': {'id': 'synthetic_2'}}]
                ready.set()
            raw = ''.join('data: ' + json.dumps(item) + '\n\n' for item in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='mycrm-codex-probe-') as home:
            with open(os.path.join(home, 'synthetic-secret.txt'), 'w', encoding='utf-8') as handle:
                handle.write(_MARKER)
            node = shutil.which('node')
            if not node:
                raise ValueError('node-unavailable')
            env = {'PATH': os.path.dirname(os.path.realpath(node)) + ':/usr/bin:/bin',
                   'HOME': home, 'CODEX_HOME': home, 'FAKE_TOKEN': 'synthetic'}
            argv = _build_appserver_argv(os.path.abspath(cli))
            for item in ('model_provider="local"', 'model_providers.local.name="local"',
                         f'model_providers.local.base_url="http://127.0.0.1:{server.server_port}/v1"',
                         'model_providers.local.env_key="FAKE_TOKEN"',
                         'model_providers.local.wire_api="responses"',
                         'model_providers.local.supports_websockets=false'):
                argv += ['-c', item]
            proc = subprocess.Popen(argv, env=env, cwd=home, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, bufsize=1, start_new_session=True)
            messages, dynamic = queue.Queue(), []
            def read():
                for line in proc.stdout:
                    try:
                        messages.put(json.loads(line))
                    except ValueError:
                        pass
            threading.Thread(target=read, daemon=True).start()
            def send(message):
                proc.stdin.write(json.dumps(message) + '\n')
                proc.stdin.flush()
            def request(identifier, method, params):
                send({'id': identifier, 'method': method, 'params': params})
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        item = messages.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if item.get('id') == identifier:
                        if 'error' in item:
                            raise ValueError('rpc-error')
                        return item.get('result')
                raise TimeoutError('rpc-timeout')
            try:
                request(1, 'initialize', {'clientInfo': {'name': 'synthetic', 'version': '1'},
                                           'capabilities': {'experimentalApi': True}})
                send({'method': 'initialized', 'params': {}})
                tools = [{'type': 'function', 'name': 'mycrm_' + name, 'description': 'Synthetic',
                          'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
                         for name in sorted(_ALLOWED)]
                thread = request(2, 'thread/start', {'model': 'gpt-6.1-sol', 'cwd': home,
                    'sandbox': 'read-only', 'dynamicTools': tools, 'environments': []})
                request(3, 'turn/start', {'threadId': thread['thread']['id'], 'model': 'gpt-6.1-sol',
                    'cwd': home, 'input': [{'type': 'text', 'text': 'Synthetic', 'text_elements': []}],
                    'environments': [], 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}})
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline and not ready.is_set():
                    try:
                        item = messages.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if item.get('method') == 'item/tool/call':
                        dynamic.append(item['params'].get('tool'))
                        send({'id': item['id'], 'result': {'success': True, 'contentItems': [
                            {'type': 'inputText', 'text': 'synthetic ok'}]}})
                outputs = json.dumps(arrivals[1].get('input', [])) if len(arrivals) > 1 else ''
                observation = {'dynamic': dynamic, 'outputs': outputs, 'requests': len(arrivals),
                               'created': os.path.exists(os.path.join(home, 'synthetic-probe.txt')),
                               'exposed': _MARKER in outputs}
                check_observation(mode, observation)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                proc.stdin.close()
                proc.stdout.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def run_lifecycle_probe(cli, *, timeout=30):
    """Exercise two resumed real-CLI turns and revoke while a turn is running."""
    requests, calls = [], []
    received, release = threading.Event(), threading.Event()
    blocking = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 1024 * 1024:
                self.send_error(400)
                return
            self.rfile.read(length)
            requests.append(len(requests) + 1)
            if blocking.is_set():
                received.set()
                release.wait(timeout)
            if len(requests) % 2:
                events = [{'type': 'response.output_item.done', 'item': {
                    'type': 'custom_tool_call', 'call_id': 'synthetic_' + str(len(requests)),
                    'name': 'exec', 'namespace': 'functions', 'input': _CALLS['read']}},
                    {'type': 'response.completed', 'response': {'id': 'synthetic_' + str(len(requests))}}]
            else:
                events = [{'type': 'response.output_item.done', 'item': {'type': 'message',
                    'id': 'answer_' + str(len(requests)), 'role': 'assistant', 'content': [
                        {'type': 'output_text', 'text': 'Synthetic done'}]}},
                    {'type': 'response.completed', 'response': {'id': 'synthetic_' + str(len(requests))}}]
            raw = ''.join('data: ' + json.dumps(item) + '\n\n' for item in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    class Relay:
        def tools(self):
            return [{'type': 'function', 'name': 'mycrm_read', 'description': 'Synthetic',
                     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]

        def call(self, name, arguments):
            calls.append((name, arguments))
            return {'success': True, 'contentItems': [{'type': 'inputText', 'text': 'synthetic ok'}]}

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='mycrm-codex-lifecycle-') as home:
            node = shutil.which('node')
            if not node:
                raise ValueError('node-unavailable')
            env = {'PATH': os.path.dirname(os.path.realpath(node)) + ':/usr/bin:/bin',
                   'HOME': home, 'CODEX_HOME': home, 'FAKE_TOKEN': 'synthetic'}
            argv = _build_appserver_argv(os.path.abspath(cli))
            for item in ('model_provider="local"', 'model_providers.local.name="local"',
                         f'model_providers.local.base_url="http://127.0.0.1:{server.server_port}/v1"',
                         'model_providers.local.env_key="FAKE_TOKEN"',
                         'model_providers.local.wire_api="responses"',
                         'model_providers.local.supports_websockets=false'):
                argv += ['-c', item]
            thread_ref = None
            for attempt in range(2):
                runner = AppServerProcess(MacOSProcessSupervisor(), Relay(), lambda: True, timeout=timeout)
                events = list(runner.run(argv, cwd=home, env=env, model='gpt-6.1-sol',
                                         text='Synthetic', thread_ref=thread_ref))
                refs = [data['cli_session_ref'] for kind, data in events if kind == 'session_ref']
                if len(refs) != 1 or (thread_ref is not None and refs[0] != thread_ref):
                    raise ValueError('resume-thread-mismatch')
                thread_ref = refs[0]
                if not events or events[-1][0] != 'done' or len(calls) != attempt + 1:
                    raise ValueError('resume-failed')
            blocking.set()
            consent = threading.Event()
            consent.set()
            runner = AppServerProcess(MacOSProcessSupervisor(), Relay(), consent.is_set, timeout=timeout)
            result = []
            def revoked_turn():
                try:
                    result.extend(runner.run(argv, cwd=home, env=env, model='gpt-6.1-sol',
                                             text='Synthetic', thread_ref=thread_ref))
                except ValueError as error:
                    result.append(('error', str(error)))
            worker = threading.Thread(target=revoked_turn)
            worker.start()
            if not received.wait(timeout):
                raise TimeoutError('revoke-test-start')
            consent.clear()
            worker.join(timeout=timeout)
            if worker.is_alive() or not result or result[-1] != ('error', 'consent-revoked'):
                raise ValueError('revoke-not-enforced')
            if any(kind == 'done' for kind, _ in result):
                raise ValueError('revoked-turn-completed')
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--package-root')
    parser.add_argument('--archive')
    parser.add_argument('--source-sha')
    parser.add_argument('--receipt')
    args = parser.parse_args()
    cli = os.path.realpath(args.cli)
    host = os.path.join(os.path.dirname(cli), 'codex-code-mode-host')
    node = shutil.which('node')
    if not node:
        raise ValueError('node-unavailable')
    with tempfile.TemporaryDirectory(prefix='mycrm-codex-version-') as home:
        env = {'PATH': os.path.dirname(os.path.realpath(node)) + ':/usr/bin:/bin',
               'HOME': home, 'CODEX_HOME': home}
        validate_version(_capture_version_output(cli, cwd=home, env=env), args.expected_version)
    if bool(args.receipt) != bool(args.package_root and args.source_sha and args.archive):
        raise ValueError('incomplete-receipt-arguments')
    if args.receipt:
        if not re.fullmatch(r'[0-9a-f]{40}', args.source_sha):
            raise ValueError('invalid-source-sha')
        actual = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, capture_output=True,
                                text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                               check=True, capture_output=True, text=True, timeout=5).stdout
        if actual != args.source_sha or dirty:
            raise ValueError('source-revision-mismatch')
        root = os.path.realpath(args.package_root)
        if os.path.commonpath((root, cli)) != root:
            raise ValueError('cli-outside-package')
        with open(cli, 'rb') as handle:
            magic = handle.read(4)
        if platform.system() != 'Darwin' or magic not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'):
            raise ValueError('native-macos-cli-required')
        package_before, node_before = digest_package(root), digest_file(os.path.realpath(node))
        native_before = digest_file(cli)
        if os.path.islink(host) or not os.path.isfile(host):
            raise ValueError('native-code-mode-host-required')
        host_before = digest_file(host)
        archive_before = digest_file(args.archive)
        config_before = source_fingerprint(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with contextlib.ExitStack() as stack:
        tested_cli = cli
        if args.archive:
            managed_home = stack.enter_context(tempfile.TemporaryDirectory(prefix='mycrm-managed-probe-'))
            os.chmod(managed_home, 0o700)
            arch = {'arm64':'arm64', 'x86_64':'x64'}.get(platform.machine())
            if arch is None:
                raise ValueError('unsupported-architecture')
            with open(args.archive, 'rb') as archive:
                tested_cli = install_native(managed_home, arch, digest_file(cli), digest_file(host), archive)
        for mode in _CALLS:
            run_probe(tested_cli, mode)
            print(mode + ': pass', flush=True)
        run_lifecycle_probe(tested_cli)
        print('resume/revoke: pass', flush=True)
        if args.receipt and (digest_file(tested_cli) != native_before or
                digest_file(os.path.join(os.path.dirname(tested_cli), 'codex-code-mode-host')) != host_before):
            raise ValueError('tested-managed-artifact-changed')
    if args.receipt:
        if (package_before != digest_package(root) or node_before != digest_file(os.path.realpath(node))
                or native_before != digest_file(cli)
                or host_before != digest_file(host)
                or archive_before != digest_file(args.archive)
                or config_before != source_fingerprint(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))):
            raise ValueError('tested-artifact-changed')
        receipt = {'source_sha': args.source_sha, 'version': args.expected_version,
                   'os': platform.system().lower(), 'arch': platform.machine().lower(),
                   'package_sha256': package_before, 'node_sha256': node_before,
                   'native_sha256': native_before, 'host_sha256': host_before, 'config_sha256': config_before,
                   'archive_sha256': archive_before,
                   'probes': [*list(_CALLS), 'resume', 'revoke']}
        with open(args.receipt, 'x', encoding='utf-8') as handle:
            json.dump(receipt, handle, sort_keys=True, separators=(',', ':'))


if __name__ == '__main__':
    main()
