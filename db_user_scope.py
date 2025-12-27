"""
User-Scoped Database Query Helpers for TallyUps
Ensures all queries are properly filtered by user_id for multi-tenant data isolation
"""

import logging
from flask import g
from functools import wraps

logger = logging.getLogger(__name__)

# Admin user ID (used for legacy auth and admin operations)
ADMIN_USER_ID = 'admin-00000000-0000-0000-0000-000000000000'


def get_current_user_id() -> str:
    """
    Get the current user's ID from the Flask request context.
    Returns ADMIN_USER_ID if no user is set (legacy compatibility).
    """
    return getattr(g, 'user_id', None) or ADMIN_USER_ID


def is_admin_user() -> bool:
    """Check if the current user is an admin."""
    return getattr(g, 'user_role', 'user') == 'admin'


def add_user_scope(query: str, params: tuple, table_alias: str = None) -> tuple:
    """
    Add user_id filtering to a SQL query.

    Args:
        query: The SQL query string
        params: Tuple of query parameters
        table_alias: Optional table alias (e.g., 't' for 't.user_id')

    Returns:
        Tuple of (modified_query, modified_params)

    Example:
        query = "SELECT * FROM transactions WHERE deleted = 0"
        query, params = add_user_scope(query, (), 't')
        # Result: "SELECT * FROM transactions WHERE deleted = 0 AND t.user_id = %s"
    """
    user_id = get_current_user_id()

    prefix = f"{table_alias}." if table_alias else ""
    user_clause = f"{prefix}user_id = %s"

    # Determine where to insert the user_id clause
    query_upper = query.upper()

    if ' WHERE ' in query_upper:
        # Add to existing WHERE clause
        where_pos = query_upper.find(' WHERE ') + 7
        # Find the end of the WHERE clause (before ORDER BY, GROUP BY, LIMIT, etc.)
        end_pos = len(query)
        for keyword in [' ORDER BY', ' GROUP BY', ' LIMIT', ' HAVING', ' UNION']:
            pos = query_upper.find(keyword)
            if pos > where_pos and pos < end_pos:
                end_pos = pos

        # Insert user_id condition
        modified_query = query[:end_pos] + f" AND {user_clause}" + query[end_pos:]
    else:
        # No WHERE clause, add one
        # Find where to insert (before ORDER BY, GROUP BY, LIMIT, etc.)
        insert_pos = len(query)
        for keyword in [' ORDER BY', ' GROUP BY', ' LIMIT', ' HAVING', ' UNION']:
            pos = query_upper.find(keyword)
            if pos > 0 and pos < insert_pos:
                insert_pos = pos

        modified_query = query[:insert_pos] + f" WHERE {user_clause}" + query[insert_pos:]

    return modified_query, params + (user_id,)


def user_scoped_query(table: str, columns: str = "*", where: str = None,
                      order_by: str = None, limit: int = None, offset: int = None,
                      table_alias: str = None) -> tuple:
    """
    Build a user-scoped SELECT query.

    Args:
        table: Table name
        columns: Column selection (default "*")
        where: Additional WHERE conditions (without "WHERE")
        order_by: ORDER BY clause (without "ORDER BY")
        limit: LIMIT value
        offset: OFFSET value
        table_alias: Optional table alias

    Returns:
        Tuple of (query, params)
    """
    user_id = get_current_user_id()
    params = []

    alias = f" AS {table_alias}" if table_alias else ""
    prefix = f"{table_alias}." if table_alias else ""

    query = f"SELECT {columns} FROM {table}{alias}"

    # Build WHERE clause
    conditions = [f"{prefix}user_id = %s"]
    params.append(user_id)

    if where:
        conditions.append(f"({where})")

    query += " WHERE " + " AND ".join(conditions)

    if order_by:
        query += f" ORDER BY {order_by}"

    if limit is not None:
        query += f" LIMIT %s"
        params.append(limit)

        if offset is not None:
            query += f" OFFSET %s"
            params.append(offset)

    return query, tuple(params)


def user_scoped_count(table: str, where: str = None) -> tuple:
    """
    Build a user-scoped COUNT query.

    Args:
        table: Table name
        where: Additional WHERE conditions

    Returns:
        Tuple of (query, params)
    """
    user_id = get_current_user_id()
    params = [user_id]

    query = f"SELECT COUNT(*) as cnt FROM {table} WHERE user_id = %s"

    if where:
        query += f" AND ({where})"

    return query, tuple(params)


def user_scoped_update(table: str, set_clause: str, where: str,
                       set_params: tuple, where_params: tuple) -> tuple:
    """
    Build a user-scoped UPDATE query.

    Args:
        table: Table name
        set_clause: SET clause (without "SET")
        where: WHERE conditions (without "WHERE")
        set_params: Parameters for SET clause
        where_params: Parameters for WHERE clause

    Returns:
        Tuple of (query, params)
    """
    user_id = get_current_user_id()

    query = f"UPDATE {table} SET {set_clause} WHERE user_id = %s AND {where}"
    params = set_params + (user_id,) + where_params

    return query, params


def user_scoped_delete(table: str, where: str, params: tuple = ()) -> tuple:
    """
    Build a user-scoped DELETE query (soft delete recommended).

    Args:
        table: Table name
        where: WHERE conditions
        params: Parameters for WHERE clause

    Returns:
        Tuple of (query, params)
    """
    user_id = get_current_user_id()

    query = f"DELETE FROM {table} WHERE user_id = %s AND {where}"
    return query, (user_id,) + params


def user_scoped_insert(table: str, columns: list, values_params: tuple) -> tuple:
    """
    Build a user-scoped INSERT query (automatically adds user_id).

    Args:
        table: Table name
        columns: List of column names (user_id will be added)
        values_params: Tuple of values (user_id will be prepended)

    Returns:
        Tuple of (query, params)
    """
    user_id = get_current_user_id()

    # Add user_id to columns and values
    all_columns = ['user_id'] + list(columns)
    placeholders = ', '.join(['%s'] * len(all_columns))
    columns_str = ', '.join(all_columns)

    query = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
    params = (user_id,) + values_params

    return query, params


class UserScopedDB:
    """
    Context manager for user-scoped database operations.
    Provides helper methods that automatically scope queries by user_id.
    """

    def __init__(self, conn, cursor):
        self.conn = conn
        self.cursor = cursor
        self.user_id = get_current_user_id()

    def execute_scoped(self, query: str, params: tuple = (), table_alias: str = None):
        """Execute a query with automatic user_id scoping."""
        scoped_query, scoped_params = add_user_scope(query, params, table_alias)
        self.cursor.execute(scoped_query, scoped_params)
        return self.cursor

    def select(self, table: str, columns: str = "*", where: str = None,
               order_by: str = None, limit: int = None, offset: int = None):
        """Execute a user-scoped SELECT query."""
        query, params = user_scoped_query(table, columns, where, order_by, limit, offset)
        self.cursor.execute(query, params)
        return self.cursor

    def count(self, table: str, where: str = None) -> int:
        """Execute a user-scoped COUNT query."""
        query, params = user_scoped_count(table, where)
        self.cursor.execute(query, params)
        result = self.cursor.fetchone()
        return result[0] if result else 0

    def update(self, table: str, set_clause: str, where: str,
               set_params: tuple = (), where_params: tuple = ()):
        """Execute a user-scoped UPDATE query."""
        query, params = user_scoped_update(table, set_clause, where, set_params, where_params)
        self.cursor.execute(query, params)
        return self.cursor.rowcount

    def insert_with_user(self, table: str, columns: list, values: tuple):
        """Execute an INSERT with automatic user_id."""
        query, params = user_scoped_insert(table, columns, values)
        self.cursor.execute(query, params)
        return self.cursor.lastrowid


def require_user_scope(f):
    """
    Decorator that ensures g.user_id is set before the route executes.
    Falls back to ADMIN_USER_ID for backward compatibility.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'user_id') or g.user_id is None:
            g.user_id = ADMIN_USER_ID
            g.user_role = 'admin'
            logger.debug(f"No user_id set, defaulting to admin for route {f.__name__}")
        return f(*args, **kwargs)
    return decorated
