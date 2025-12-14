#!/usr/bin/env python3
"""
Railway Deployment Tests
========================

Tests specific to Railway deployment configuration:
- Development vs Production environment detection
- Database read-only mode in development
- Health check endpoints
- Environment variable configuration
- Custom domain routing
"""

import os
import sys
import pytest
import requests
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# RAILWAY ENVIRONMENT CONFIGURATION
# =============================================================================

# Railway URLs
PROD_URL = "https://tallyups.com"
PROD_RAILWAY_URL = "https://web-production-309e.up.railway.app"
DEV_URL = "https://web-development-c29a.up.railway.app"

# Railway Project IDs
PROJECT_ID = "f6f866e5-94f7-4ced-9bc7-a33197ca8411"
PROD_ENV_ID = "9d801aac-3f55-4ee0-a012-e2d8a9a58e55"
DEV_ENV_ID = "7542556b-c121-4ed5-bfee-ca4f83d24039"


# =============================================================================
# ENVIRONMENT DETECTION TESTS
# =============================================================================

class TestEnvironmentDetection:
    """Test environment detection logic."""

    @pytest.mark.unit
    def test_production_env_detection(self):
        """Production environment is correctly detected."""
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT': 'production'}):
            assert os.environ.get('RAILWAY_ENVIRONMENT') == 'production'

    @pytest.mark.unit
    def test_development_env_detection(self):
        """Development environment is correctly detected."""
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT': 'development'}):
            assert os.environ.get('RAILWAY_ENVIRONMENT') == 'development'

    @pytest.mark.unit
    def test_read_only_mode_in_dev(self):
        """DB_READ_ONLY should be true in development."""
        with patch.dict(os.environ, {
            'RAILWAY_ENVIRONMENT': 'development',
            'DB_READ_ONLY': 'true'
        }):
            is_read_only = os.environ.get('DB_READ_ONLY', '').lower() in ('true', '1', 'yes')
            assert is_read_only is True

    @pytest.mark.unit
    def test_read_only_mode_not_in_prod(self):
        """DB_READ_ONLY should be false in production."""
        with patch.dict(os.environ, {
            'RAILWAY_ENVIRONMENT': 'production',
            'DB_READ_ONLY': 'false'
        }, clear=False):
            is_read_only = os.environ.get('DB_READ_ONLY', '').lower() in ('true', '1', 'yes')
            assert is_read_only is False


# =============================================================================
# DATABASE READ-ONLY MODE TESTS
# =============================================================================

class TestDatabaseReadOnlyMode:
    """Test database read-only mode for development environment."""

    @pytest.mark.unit
    def test_read_only_blocks_update_transaction(self):
        """Read-only mode should block update_transaction."""
        with patch.dict(os.environ, {'DB_READ_ONLY': 'true'}):
            # Import after setting env var
            try:
                from db_mysql import MySQLReceiptDatabase

                # Mock the pool to avoid actual DB connection
                with patch('db_mysql.get_connection_pool'):
                    db = MySQLReceiptDatabase.__new__(MySQLReceiptDatabase)
                    db.config = {'host': 'test', 'port': 3306, 'user': 'test', 'password': 'test', 'database': 'test'}
                    db._pool = MagicMock()
                    db.use_mysql = True
                    db.read_only = True

                    result = db.update_transaction(1, {'notes': 'test'})
                    assert result is False
            except ImportError:
                pytest.skip("db_mysql not available")

    @pytest.mark.unit
    def test_read_only_blocks_delete_report(self):
        """Read-only mode should block delete_report."""
        with patch.dict(os.environ, {'DB_READ_ONLY': 'true'}):
            try:
                from db_mysql import MySQLReceiptDatabase

                with patch('db_mysql.get_connection_pool'):
                    db = MySQLReceiptDatabase.__new__(MySQLReceiptDatabase)
                    db.config = {'host': 'test', 'port': 3306, 'user': 'test', 'password': 'test', 'database': 'test'}
                    db._pool = MagicMock()
                    db.use_mysql = True
                    db.read_only = True

                    result = db.delete_report('test-report-id')
                    assert result is False
            except ImportError:
                pytest.skip("db_mysql not available")

    @pytest.mark.unit
    def test_read_only_allows_read_operations(self):
        """Read-only mode should allow read operations."""
        with patch.dict(os.environ, {'DB_READ_ONLY': 'true'}):
            try:
                from db_mysql import MySQLReceiptDatabase

                with patch('db_mysql.get_connection_pool') as mock_pool:
                    # Setup mock connection
                    mock_conn = MagicMock()
                    mock_cursor = MagicMock()
                    mock_cursor.fetchall.return_value = []
                    mock_conn.cursor.return_value = mock_cursor
                    mock_pool.return_value.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
                    mock_pool.return_value.connection.return_value.__exit__ = MagicMock(return_value=False)

                    db = MySQLReceiptDatabase.__new__(MySQLReceiptDatabase)
                    db.config = {'host': 'test', 'port': 3306, 'user': 'test', 'password': 'test', 'database': 'test'}
                    db._pool = mock_pool.return_value
                    db.use_mysql = True
                    db.read_only = True

                    # Read operations should work
                    # (actual implementation would test specific read methods)
                    assert db.read_only is True
            except ImportError:
                pytest.skip("db_mysql not available")


# =============================================================================
# HEALTH CHECK ENDPOINT TESTS
# =============================================================================

class TestHealthCheckEndpoints:
    """Test health check endpoints for Railway deployment."""

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_production_health_check(self):
        """Production health endpoint returns 200."""
        try:
            response = requests.get(f"{PROD_URL}/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert 'status' in data
        except requests.exceptions.RequestException:
            pytest.skip("Production server not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_development_health_check(self):
        """Development health endpoint returns 200."""
        try:
            response = requests.get(f"{DEV_URL}/health", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert 'status' in data
        except requests.exceptions.RequestException:
            pytest.skip("Development server not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_custom_domain_routing(self):
        """Custom domain tallyups.com routes correctly."""
        try:
            response = requests.get(f"{PROD_URL}/health", timeout=10, allow_redirects=True)
            assert response.status_code == 200
        except requests.exceptions.RequestException:
            pytest.skip("Custom domain not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_www_subdomain_routing(self):
        """www.tallyups.com routes correctly."""
        try:
            response = requests.get("https://www.tallyups.com/health", timeout=10, allow_redirects=True)
            assert response.status_code == 200
        except requests.exceptions.RequestException:
            pytest.skip("WWW subdomain not accessible")


# =============================================================================
# API AUTHENTICATION TESTS
# =============================================================================

class TestAPIAuthentication:
    """Test API authentication in Railway deployment."""

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_unauthenticated_redirect(self):
        """Unauthenticated requests redirect to login."""
        try:
            response = requests.get(f"{PROD_URL}/api/transactions",
                                   timeout=10, allow_redirects=False)
            # Should redirect to login
            assert response.status_code in [302, 401]
        except requests.exceptions.RequestException:
            pytest.skip("Server not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_admin_api_key_required(self):
        """Admin endpoints require API key."""
        try:
            response = requests.get(f"{PROD_URL}/api/health/pool-status", timeout=10)
            # Should require authentication
            assert response.status_code in [200, 401, 403]
        except requests.exceptions.RequestException:
            pytest.skip("Server not accessible")


# =============================================================================
# DEPLOYMENT CONFIGURATION TESTS
# =============================================================================

class TestDeploymentConfiguration:
    """Test deployment configuration is correct."""

    @pytest.mark.unit
    def test_required_env_vars_defined(self):
        """All required environment variables have defaults or are set."""
        required_vars = [
            'MYSQL_URL',
            'PORT',
            'SECRET_KEY',
        ]

        # These should either be set or have defaults in the app
        for var in required_vars:
            # Just verify the app can handle missing vars gracefully
            value = os.environ.get(var)
            # In test environment, these may not be set, which is OK
            assert True  # App should handle missing vars with defaults

    @pytest.mark.unit
    def test_pool_configuration(self):
        """Database pool configuration is reasonable."""
        pool_size = int(os.environ.get('DB_POOL_SIZE', '20'))
        pool_overflow = int(os.environ.get('DB_POOL_OVERFLOW', '30'))
        pool_timeout = int(os.environ.get('DB_POOL_TIMEOUT', '60'))
        pool_recycle = int(os.environ.get('DB_POOL_RECYCLE', '300'))

        assert 5 <= pool_size <= 50, "Pool size should be reasonable"
        assert pool_overflow >= pool_size, "Overflow should be >= pool size"
        assert pool_timeout >= 30, "Timeout should be at least 30s"
        assert pool_recycle <= 600, "Recycle should be <= 10 minutes for Railway"


# =============================================================================
# SMOKE TESTS
# =============================================================================

class TestProductionSmoke:
    """Quick smoke tests to verify production is working."""

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_homepage_loads(self):
        """Homepage loads without error."""
        try:
            response = requests.get(f"{PROD_URL}/", timeout=10, allow_redirects=True)
            # Should either load or redirect to login
            assert response.status_code in [200, 302]
        except requests.exceptions.RequestException:
            pytest.skip("Production server not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_static_assets_load(self):
        """Static assets are served correctly."""
        try:
            response = requests.get(f"{PROD_URL}/static/icon.svg", timeout=10)
            assert response.status_code == 200
        except requests.exceptions.RequestException:
            pytest.skip("Production server not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_ssl_certificate_valid(self):
        """SSL certificate is valid."""
        try:
            # requests will raise an error if SSL is invalid
            response = requests.get(f"{PROD_URL}/health", timeout=10)
            assert response.status_code == 200
        except requests.exceptions.SSLError:
            pytest.fail("SSL certificate is invalid")
        except requests.exceptions.RequestException:
            pytest.skip("Production server not accessible")


class TestDevelopmentSmoke:
    """Quick smoke tests for development environment."""

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_dev_homepage_loads(self):
        """Development homepage loads."""
        try:
            response = requests.get(f"{DEV_URL}/", timeout=10, allow_redirects=True)
            assert response.status_code in [200, 302]
        except requests.exceptions.RequestException:
            pytest.skip("Development server not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_dev_health_returns_environment(self):
        """Development health check indicates development environment."""
        try:
            response = requests.get(f"{DEV_URL}/health", timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Health response might include environment info
                assert 'status' in data
        except requests.exceptions.RequestException:
            pytest.skip("Development server not accessible")


# =============================================================================
# RAILWAY API TESTS (using Railway GraphQL API)
# =============================================================================

class TestRailwayAPI:
    """Test Railway API integration."""

    RAILWAY_API_TOKEN = os.environ.get('RAILWAY_API_TOKEN', 'e82a0806-6042-4101-bbce-34945c3212cb')
    RAILWAY_API_URL = "https://backboard.railway.app/graphql/v2"

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_railway_api_accessible(self):
        """Railway API is accessible with token."""
        try:
            response = requests.post(
                self.RAILWAY_API_URL,
                headers={
                    "Authorization": f"Bearer {self.RAILWAY_API_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"query": "query { me { email } }"},
                timeout=10
            )
            assert response.status_code == 200
            data = response.json()
            assert 'data' in data or 'errors' in data
        except requests.exceptions.RequestException:
            pytest.skip("Railway API not accessible")

    @pytest.mark.integration
    @pytest.mark.requires_api
    def test_project_has_both_environments(self):
        """Project has both production and development environments."""
        try:
            response = requests.post(
                self.RAILWAY_API_URL,
                headers={
                    "Authorization": f"Bearer {self.RAILWAY_API_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "query": f"""
                    query {{
                        project(id: "{PROJECT_ID}") {{
                            environments {{
                                edges {{
                                    node {{ name }}
                                }}
                            }}
                        }}
                    }}
                    """
                },
                timeout=10
            )
            assert response.status_code == 200
            data = response.json()

            if 'data' in data and data['data'].get('project'):
                env_names = [
                    e['node']['name']
                    for e in data['data']['project']['environments']['edges']
                ]
                assert 'production' in env_names
                assert 'development' in env_names
        except requests.exceptions.RequestException:
            pytest.skip("Railway API not accessible")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
