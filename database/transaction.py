"""Opt-in unit of work spanning existing repositories in the same thread."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_CURRENT = ContextVar("database_unit_of_work", default=None)


class JoinedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, parameters=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            return self.connection.execute("SELECT 1")
        return self.connection.execute(sql, parameters)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *args):
        self.failed |= exc_type is not None


def joined_connection(path):
    current = _CURRENT.get()
    return current[1] if current and current[0] == Path(path).resolve() else None


@contextmanager
def atomic_database(path):
    from database.repository import SQLiteRepository

    if _CURRENT.get():
        raise RuntimeError("Uma atualização transacional já está em andamento")
    with SQLiteRepository(path) as repo:
        repo.connection.execute("BEGIN IMMEDIATE")
        joined = JoinedConnection(repo.connection)
        token = _CURRENT.set((Path(path).resolve(), joined))
        try:
            yield
            if joined.failed:
                raise RuntimeError("Uma etapa falhou; atualização revertida")
            repo.connection.commit()
        except BaseException:
            repo.connection.rollback()
            raise
        finally:
            _CURRENT.reset(token)
