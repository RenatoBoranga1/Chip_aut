"""Local OS-owned locks. Never unlink lock files or steal an active lock by age."""

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


class ExecutionLock:
    def __init__(self, database, kind="pipeline"):
        self.path = Path(str(Path(database).resolve()) + f".{kind}.lock")
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "a+b")
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise AlreadyRunning("Atualização já em andamento") from exc
            raise
        return self

    def __exit__(self, *args):
        if self.file:
            try:
                if os.name == "nt":
                    import msvcrt

                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.file.close()
                self.file = None


@contextmanager
def migration_lock(database):
    lock = ExecutionLock(database, "schema")
    deadline = time.monotonic() + 30
    while True:
        try:
            lock.__enter__()
            break
        except AlreadyRunning:
            if time.monotonic() >= deadline:
                raise RuntimeError("A atualização do banco está ocupada; tente novamente") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.__exit__()
