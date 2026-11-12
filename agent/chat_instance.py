"""한 home 에 상주 chat 하나 (J-F7 고아 정리).

chat 은 시작할 때 `locks/chat.lock` 에 POSIX 레코드 잠금(lockf)을 잡고 끝날 때까지 쥔다. 잠금은 프로세스가 어떻게
끝나든 OS 가 푼다. 앞 실행이 남긴 chat(데스크톱 앱이 먼저 죽어 ppid 1 로 남은 것)이 아직 잠금을 쥐고 있으면, 새 chat 은
커널이 알려 주는 잠금 보유자 pid(F_GETLK)에만 SIGTERM 을 보낸다. 파일 내용이나 프로세스 이름으로 고르지 않으므로
재사용된 pid 나 남의 프로세스를 건드리지 않는다. SIGTERM 을 받은 chat 은 진행 중 CLI 프로세스 그룹을 끝내고 나간다.
정해진 시간 안에 잠금이 풀리지 않으면 SIGKILL 을 한 번 보내고, 그래도 안 풀리면 시작하지 않는다(unconfirmed).
잠금 파일은 O_NOFOLLOW 로 열고 fstat 로 정규 파일인지, 소유자가 현재 사용자인지 본다(R-J4). 어긋나면(symlink, 디렉터리,
FIFO, 남의 파일) 신호를 보내지 않고, 파일을 고치지 않고 시작하지 않는다(unsafe) — 다른 잠금 보유자에 신호를 보내지 않게.

Windows 는 대화 다리가 없어 chat 이 돌지 않으므로 잠금 없이 지나간다(unsupported).
"""
from __future__ import annotations

import errno
import os
import signal
import stat
import struct
import sys
import time

LOCK_NAME = "chat.lock"
# O_NOFOLLOW 가 symlink 를 거절하는 errno(Linux, macOS = ELOOP, FreeBSD = EMLINK, NetBSD = EFTYPE)와 디렉터리, 소켓
_UNSAFE_OPEN = frozenset(getattr(errno, n) for n in ("ELOOP", "EMLINK", "EFTYPE", "EISDIR", "ENXIO", "EOPNOTSUPP") if hasattr(errno, n))


class InstanceUnavailable(RuntimeError):
    """앞 실행의 chat 이 끝나는 것을 확인하지 못했다."""


def _flock_layout():
    """struct flock 의 필드 순서와 크기. 지원하지 않는 OS 면 None."""
    if sys.platform == "darwin" or sys.platform.startswith(("freebsd", "openbsd", "netbsd")):
        # off_t l_start; off_t l_len; pid_t l_pid; short l_type; short l_whence;
        return "@qqihh", ("start", "len", "pid", "type", "whence"), 24
    if sys.platform.startswith("linux"):
        # short l_type; short l_whence; off_t l_start; off_t l_len; pid_t l_pid; (+ 끝 패딩, 64-bit 32바이트)
        return "@hhqqi", ("type", "whence", "start", "len", "pid"), 32
    return None


def holder_pid(fd: int):
    """fd 가 가리키는 파일 전체에 쓰기 잠금을 쥔 다른 프로세스의 pid. 쥔 프로세스가 없으면 None."""
    import fcntl
    layout = _flock_layout()
    if layout is None:
        return None
    fmt, names, size = layout
    values = {"type": fcntl.F_WRLCK, "whence": os.SEEK_SET, "start": 0, "len": 0, "pid": 0}
    raw = struct.pack(fmt, *(values[n] for n in names))
    raw = raw + b"\0" * max(0, size - len(raw))
    out = fcntl.fcntl(fd, fcntl.F_GETLK, raw)
    got = dict(zip(names, struct.unpack(fmt, out[:struct.calcsize(fmt)])))
    if got["type"] == fcntl.F_UNLCK:
        return None
    pid = got["pid"]
    return pid if isinstance(pid, int) and pid > 1 and pid != os.getpid() else None


class ChatInstance:
    """claim() 으로 잠금을 잡고(필요하면 앞 실행을 끝내고) release() 로 놓는다."""

    def __init__(self, locks_dir: str, *, kill=os.kill, sleep=time.sleep, monotonic=time.monotonic,
                 term_wait: float = 15.0, kill_wait: float = 5.0, poll: float = 0.1):
        self.path = os.path.join(locks_dir, LOCK_NAME)
        self.kill, self.sleep, self.monotonic = kill, sleep, monotonic
        self.term_wait, self.kill_wait, self.poll = term_wait, kill_wait, poll
        self._fd = None
        self.reaped = None   # 끝낸 앞 실행의 pid(없으면 None)

    @staticmethod
    def supported() -> bool:
        return os.name != "nt" and _flock_layout() is not None

    def _try_lock(self, fd) -> bool:
        import fcntl
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 0, 0, os.SEEK_SET)
            return True
        except OSError:
            return False

    def _wait(self, fd, seconds) -> bool:
        deadline = self.monotonic() + seconds
        while True:
            if self._try_lock(fd):
                return True
            if self.monotonic() >= deadline:
                return False
            self.sleep(self.poll)

    def _signal(self, fd, sig) -> None:
        pid = holder_pid(fd)
        if pid is None:
            return
        self.reaped = pid
        try:
            self.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            raise InstanceUnavailable("permission")

    def claim(self) -> "ChatInstance":
        """잠금을 잡는다. 앞 실행이 쥐고 있으면 그 보유자만 끝낸다. 끝내지 못하면 InstanceUnavailable."""
        if not self.supported():
            return self
        # O_NONBLOCK: 경로가 FIFO 여도 open 이 멈추지 않는다(정규 파일에는 영향 없음). symlink = ELOOP, 디렉터리 = EISDIR
        flags = (os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_CLOEXEC", 0))
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as e:
            if e.errno in _UNSAFE_OPEN:
                raise InstanceUnavailable("unsafe") from e
            raise
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
                raise InstanceUnavailable("unsafe")   # 잠금, 신호, truncate 보다 먼저
            if not self._try_lock(fd):
                self._signal(fd, signal.SIGTERM)
                if not self._wait(fd, self.term_wait):
                    self._signal(fd, signal.SIGKILL)
                    if not self._wait(fd, self.kill_wait):
                        raise InstanceUnavailable("unconfirmed")
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))   # 사람이 볼 진단용. 판정에는 쓰지 않는다
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            os.ftruncate(fd, 0)
        except OSError:
            pass
        os.close(fd)   # 이 프로세스의 레코드 잠금이 풀린다
