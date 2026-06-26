"""Подключение к PostgreSQL через простой пул psycopg.

Строка подключения берётся из переменной окружения DATABASE_URL,
по умолчанию — локальный Postgres.app (порт 5433, база arman, без пароля).
"""
import os
from contextlib import contextmanager

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://arman@localhost:5433/arman",
)

# Пул создаётся один раз на процесс
pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True)


@contextmanager
def get_cursor():
    """Курсор, возвращающий строки как dict. Коммитит при успешном выходе."""
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur
        conn.commit()
