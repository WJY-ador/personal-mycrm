"""자격 증명 보관 — macOS Keychain(`security` CLI). 평문 파일 대체 없음.

비밀값은 명령줄 인자에 넣지 않는다: 쓰기는 `security -i` 의 표준 입력으로 명령을 넘기고,
읽기는 `find-generic-password -w` 의 표준 출력으로 받는다.
Windows는 현재 사용자 Credential Manager의 generic credential을 사용한다.
"""
from __future__ import annotations

import re
import subprocess

from . import osutil

_SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_SECRET = re.compile(r"^[A-Za-z0-9_.-]{16,512}$")
SECURITY_BIN = "/usr/bin/security"
_NOT_FOUND = 44   # errSecItemNotFound 의 security CLI 종료 코드


class KeyStoreError(RuntimeError):
    """Keychain 접근 불가·거부. 메시지에 비밀값을 넣지 않는다."""


class KeyStoreUnavailable(KeyStoreError):
    pass


def _run(argv, stdin_text=None, timeout=30):
    return subprocess.run(argv, input=stdin_text, capture_output=True, text=True, timeout=timeout)


class KeyStore:
    def get(self, account: str) -> str | None:
        raise NotImplementedError

    def set(self, account: str, secret: str) -> None:
        raise NotImplementedError

    def delete(self, account: str) -> bool:
        raise NotImplementedError


class MacKeychain(KeyStore):
    def __init__(self, service: str, runner=None):
        if not _SAFE.match(service or ""):
            raise KeyStoreError("service name")
        self.service = service
        self.runner = runner or _run

    def _acct(self, account: str) -> str:
        if not _SAFE.match(account or ""):
            raise KeyStoreError("account name")
        return account

    def get(self, account: str) -> str | None:
        a = self._acct(account)
        try:
            r = self.runner([SECURITY_BIN, "find-generic-password", "-s", self.service, "-a", a, "-w"])
        except (OSError, subprocess.SubprocessError):
            raise KeyStoreError("keychain read failed") from None
        if r.returncode == _NOT_FOUND:
            return None
        if r.returncode != 0:
            raise KeyStoreError(f"keychain read failed (exit {r.returncode})")
        val = (r.stdout or "").rstrip("\n")
        return val or None

    def set(self, account: str, secret: str) -> None:
        a = self._acct(account)
        if not isinstance(secret, str) or not _SAFE_SECRET.match(secret):
            raise KeyStoreError("secret has unsupported characters")
        # -U: 있으면 갱신. 비밀값은 표준 입력 명령 안에만 있다(argv 엔 없음).
        cmd = f'add-generic-password -U -s "{self.service}" -a "{a}" -w "{secret}"\n'
        try:
            r = self.runner([SECURITY_BIN, "-i"], stdin_text=cmd)
        except (OSError, subprocess.SubprocessError):
            raise KeyStoreError("keychain write failed") from None
        if r.returncode != 0:
            raise KeyStoreError(f"keychain write failed (exit {r.returncode})")
        # 쓰기 확인 — 접근 불가면 여기서 실패 종료
        if self.get(a) != secret:
            raise KeyStoreError("keychain write not readable")

    def delete(self, account: str) -> bool:
        a = self._acct(account)
        try:
            r = self.runner([SECURITY_BIN, "delete-generic-password", "-s", self.service, "-a", a])
        except (OSError, subprocess.SubprocessError):
            raise KeyStoreError("keychain delete failed") from None
        if r.returncode == _NOT_FOUND:
            return False
        if r.returncode != 0:
            raise KeyStoreError(f"keychain delete failed (exit {r.returncode})")
        return True


class _WindowsCredentialAPI:
    """Win32 calls are lazy: importing this module never opens a credential store."""

    NOT_FOUND = 1168

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        if not osutil.IS_WINDOWS or not hasattr(ctypes, "WinDLL"):
            raise KeyStoreUnavailable("Windows Credential Manager is unavailable on this OS")
        self.ctypes = ctypes

        class Credential(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.c_void_p),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self.Credential = Credential
        try:
            self.dll = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            pointer = ctypes.POINTER(Credential)
            self.dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                          wintypes.DWORD, ctypes.POINTER(pointer)]
            self.dll.CredReadW.restype = wintypes.BOOL
            self.dll.CredWriteW.argtypes = [pointer, wintypes.DWORD]
            self.dll.CredWriteW.restype = wintypes.BOOL
            self.dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self.dll.CredDeleteW.restype = wintypes.BOOL
            self.dll.CredFree.argtypes = [ctypes.c_void_p]
            self.dll.CredFree.restype = None
        except (OSError, AttributeError):
            raise KeyStoreUnavailable("Windows Credential Manager is unavailable") from None

    def _error(self, operation):
        code = self.ctypes.get_last_error()
        if code == self.NOT_FOUND:
            return False
        raise KeyStoreError("credential " + operation + " failed (Windows error " + str(code) + ")")

    def read(self, target):
        c = self.ctypes
        result = c.POINTER(self.Credential)()
        if not self.dll.CredReadW(target, 1, 0, c.byref(result)):
            self._error("read")
            return None
        try:
            entry = result.contents
            if entry.CredentialBlobSize > 2560:
                raise KeyStoreError("credential blob is too large")
            return c.string_at(entry.CredentialBlob, entry.CredentialBlobSize).decode("utf-8")
        except UnicodeError:
            raise KeyStoreError("credential encoding is invalid") from None
        finally:
            self.dll.CredFree(result)

    def write(self, target, account, secret):
        c = self.ctypes
        raw = secret.encode("utf-8")
        blob = c.create_string_buffer(raw)
        entry = self.Credential()
        entry.Type = 1  # CRED_TYPE_GENERIC
        entry.TargetName = target
        entry.UserName = account
        entry.CredentialBlobSize = len(raw)
        entry.CredentialBlob = c.cast(blob, c.c_void_p)
        entry.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE: persists for this user on this PC
        try:
            if not self.dll.CredWriteW(c.byref(entry), 0):
                # NOT_FOUND is not a successful write.
                code = c.get_last_error()
                raise KeyStoreError("credential write failed (Windows error " + str(code) + ")")
        finally:
            c.memset(c.addressof(blob), 0, c.sizeof(blob))

    def delete(self, target):
        if self.dll.CredDeleteW(target, 1, 0):
            return True
        return self._error("delete")


class WindowsCredentialStore(KeyStore):
    """Current user's generic credentials. No subprocess or plaintext fallback."""

    def __init__(self, service: str, runner=None, *, api=None):
        if not _SAFE.fullmatch(service or ""):
            raise KeyStoreError("service name")
        self.service = service
        self._backend = api

    def _api(self):
        if self._backend is None:
            self._backend = _WindowsCredentialAPI()
        return self._backend

    def _target(self, account):
        if not isinstance(account, str) or not _SAFE.fullmatch(account):
            raise KeyStoreError("account name")
        return self.service + ":" + account

    def get(self, account):
        target = self._target(account)
        return self._api().read(target)

    def set(self, account, secret):
        target = self._target(account)
        if not isinstance(secret, str) or not _SAFE_SECRET.fullmatch(secret):
            raise KeyStoreError("secret has unsupported characters")
        api = self._api()
        api.write(target, account, secret)
        if api.read(target) != secret:
            raise KeyStoreError("credential write not readable")

    def delete(self, account):
        target = self._target(account)
        return self._api().delete(target)


class UnsupportedKeyStore(KeyStore):
    def __init__(self, service: str, runner=None):
        self.service = service

    def _no(self):
        raise KeyStoreUnavailable("no supported credential store on this OS")

    def get(self, account):
        self._no()

    def set(self, account, secret):
        self._no()

    def delete(self, account):
        self._no()


def for_platform(service: str, runner=None) -> KeyStore:
    if osutil.IS_MAC:
        return MacKeychain(service, runner)
    if osutil.IS_WINDOWS:
        return WindowsCredentialStore(service, runner)
    return UnsupportedKeyStore(service, runner)
