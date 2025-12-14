#!/usr/bin/env python3
"""Test MySQL connectivity"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture
def mysql_url():
    """Get MySQL URL from environment."""
    url = os.getenv('MYSQL_URL')
    if not url:
        pytest.skip("No MYSQL_URL environment variable")
    return url


@pytest.mark.skipif(not os.getenv('MYSQL_URL'), reason="MYSQL_URL not set")
def test_mysql_connection(mysql_url):
    """Test MySQL connectivity."""
    import pymysql
    from urllib.parse import urlparse

    parsed = urlparse(mysql_url)

    conn = pymysql.connect(
        host=parsed.hostname,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],
        connect_timeout=10
    )

    # Check tables
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    assert len(tables) > 0, "Should have at least one table"

    conn.close()


if __name__ == "__main__":
    """Run standalone for debugging."""
    print("1. Loading environment...")
    load_dotenv()

    print("2. Getting MySQL URL...")
    mysql_url = os.getenv('MYSQL_URL')
    print(f"   URL found: {bool(mysql_url)}")

    if not mysql_url:
        print("   ERROR: No MYSQL_URL environment variable")
        exit(1)

    print("3. Running test...")
    test_mysql_connection(mysql_url)
    print("\n✓ SUCCESS: MySQL is working!")
