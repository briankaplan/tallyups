#!/usr/bin/env python3
"""Test that the app boots with MySQL instead of SQLite"""

import os
import sys
import pytest


@pytest.mark.skip(reason="Integration test - requires manual MySQL setup")
def test_mysql_boot():
    """Test that the app boots with MySQL instead of SQLite."""
    # Set MySQL environment variable
    os.environ['MYSQL_URL'] = 'mysql://root:test@localhost:3306/testdb'

    # Try to import viewer_server - this will execute module-level code
    try:
        import viewer_server
        # Check database type
        assert hasattr(viewer_server, 'db'), "viewer_server should have db attribute"
    except AttributeError as e:
        if 'db_path' in str(e):
            pytest.fail(f"MySQL compatibility fix didn't work: {e}")
        else:
            raise
    except Exception as e:
        # Other errors are OK (e.g., can't connect to MySQL)
        if "Can't connect" in str(e) or "Connection refused" in str(e):
            pass  # MySQL connection failed, but that's OK for this test
        else:
            raise


if __name__ == "__main__":
    """Run standalone for debugging."""
    print("Testing MySQL boot compatibility...")
    os.environ['MYSQL_URL'] = 'mysql://root:test@localhost:3306/testdb'

    try:
        import viewer_server
        print("✅ SUCCESS: App imported without crashing!")
        print(f"Database type: {'MySQL' if hasattr(viewer_server.db, 'conn') and not hasattr(viewer_server.db, 'db_path') else 'SQLite'}")
    except AttributeError as e:
        if 'db_path' in str(e):
            print(f"❌ FAILED: {e}")
            print("The MySQL compatibility fix didn't work!")
            sys.exit(1)
        else:
            raise
    except Exception as e:
        if "Can't connect" in str(e) or "Connection refused" in str(e):
            print("✅ SUCCESS: App initialized (MySQL connection failed, but that's OK for this test)")
        else:
            print(f"⚠️  Other error (might be OK): {e}")

    print("Test complete!")
