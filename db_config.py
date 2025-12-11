#!/usr/bin/env python3
"""
Centralized Database Configuration
===================================
Single source of truth for MySQL database configuration.

Usage:
    from db_config import get_db_config, get_db_connection

    # Get config dict
    config = get_db_config()

    # Or get a direct connection
    conn = get_db_connection()
"""

import os
from typing import Optional, Dict, Any
from urllib.parse import urlparse


def get_db_config() -> Optional[Dict[str, Any]]:
    """
    Get MySQL database configuration from environment variables.

    Checks in order:
    1. MYSQL_URL (Railway format: mysql://user:pass@host:port/database)
    2. Individual MYSQL* variables (MYSQLHOST, MYSQLUSER, etc.)
    3. DATABASE_URL (generic format)

    Returns:
        Dict with keys: host, port, user, password, database, charset
        None if not configured
    """
    # Try MYSQL_URL first (Railway format)
    mysql_url = os.environ.get('MYSQL_URL')
    if mysql_url:
        try:
            parsed = urlparse(mysql_url)
            return {
                'host': parsed.hostname,
                'port': parsed.port or 3306,
                'user': parsed.username,
                'password': parsed.password,
                'database': parsed.path.lstrip('/') if parsed.path else 'receipts',
                'charset': 'utf8mb4'
            }
        except Exception as e:
            print(f"⚠️  Failed to parse MYSQL_URL: {e}")

    # Try individual Railway variables
    host = os.environ.get('MYSQLHOST')
    user = os.environ.get('MYSQLUSER')
    password = os.environ.get('MYSQLPASSWORD')
    database = os.environ.get('MYSQLDATABASE', os.environ.get('MYSQL_DATABASE', 'railway'))
    port = os.environ.get('MYSQLPORT', '3306')

    if host and user:
        return {
            'host': host,
            'port': int(port),
            'user': user,
            'password': password,
            'database': database,
            'charset': 'utf8mb4'
        }

    # Try DATABASE_URL (generic format)
    database_url = os.environ.get('DATABASE_URL')
    if database_url and 'mysql' in database_url:
        try:
            parsed = urlparse(database_url)
            return {
                'host': parsed.hostname,
                'port': parsed.port or 3306,
                'user': parsed.username,
                'password': parsed.password,
                'database': parsed.path.lstrip('/') if parsed.path else 'receipts',
                'charset': 'utf8mb4'
            }
        except Exception as e:
            print(f"⚠️  Failed to parse DATABASE_URL: {e}")

    return None


def get_db_connection():
    """
    Get a direct database connection using pymysql.

    Returns:
        pymysql.Connection or None if not configured

    Note: For production code, use db_mysql.MySQLDatabase which has
    connection pooling. This function is for simple scripts only.
    """
    import pymysql
    from pymysql.cursors import DictCursor

    config = get_db_config()
    if not config:
        print("⚠️  Database not configured (set MYSQL_URL or MYSQL* environment variables)")
        return None

    try:
        conn = pymysql.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            charset=config['charset'],
            cursorclass=DictCursor
        )
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return None


def is_db_configured() -> bool:
    """Check if database environment variables are set."""
    return get_db_config() is not None


# For backwards compatibility with scripts that import directly
def get_mysql_config():
    """Alias for get_db_config() for backwards compatibility."""
    return get_db_config()
