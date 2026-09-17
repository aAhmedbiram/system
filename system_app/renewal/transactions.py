"""Renewal-owned transaction handling for workflow writes."""

from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

from system_app.queries import get_connection_pool, get_database_url


def run_renewal_transaction(callback, *args, **kwargs):
    """Run one Renewal callback in a safely finalized database transaction."""
    connection_pool = get_connection_pool()
    conn = None
    cursor = None
    pooled_connection = False
    broken_connection = False

    try:
        if connection_pool is not None:
            try:
                conn = connection_pool.getconn()
                pooled_connection = True
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                conn = psycopg2.connect(get_database_url())
        else:
            conn = psycopg2.connect(get_database_url())

        cursor = conn.cursor(cursor_factory=RealDictCursor)
        result = callback(cursor, *args, **kwargs)
        conn.commit()
        return result
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken_connection = True
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            if pooled_connection:
                try:
                    connection_pool.putconn(conn, close=broken_connection)
                except Exception:
                    try:
                        if not broken_connection:
                            conn.close()
                    except Exception:
                        pass
            else:
                try:
                    conn.close()
                except Exception:
                    pass
