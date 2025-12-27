# ReceiptAI Test Suite

Comprehensive testing suite for ReceiptAI expense reconciliation system.

## Quick Start

```bash
# Install test dependencies
pip install -r tests/requirements-test.txt

# Run all unit tests
./scripts/run_tests.sh unit

# Run with coverage
./scripts/run_tests.sh coverage

# Quick parallel tests
./scripts/run_tests.sh quick
```

## Test Structure

```
tests/
├── conftest.py                  # Shared fixtures and configuration
├── requirements-test.txt        # Test dependencies
├── README.md                    # This file
│
├── # Unit Tests
├── test_smart_matcher_v2.py     # Receipt-transaction matching (50+ tests)
├── test_business_classifier.py  # Business type classification (100+ tests)
├── test_smart_notes_service.py  # AI note generation (30+ tests)
│
├── # Integration Tests
├── test_integration.py          # Module interaction tests
├── test_api_contracts.py        # API response format tests
├── test_railway_deployment.py   # Railway dev/prod environment tests
│
├── # End-to-End Tests
├── test_e2e.py                  # Full user flow tests
│
├── # Quality Tests
├── test_performance.py          # Speed and load benchmarks
├── test_data_quality.py         # Matching accuracy validation
│
└── # Legacy/Specific Tests
    ├── test_api.py
    ├── test_gmail.py
    ├── test_mysql_*.py
    └── ...
```

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
Fast tests for individual functions. No external dependencies.

```bash
./scripts/run_tests.sh unit
# or
pytest tests/ -m "unit" -v
```

**Coverage:**
- `smart_auto_matcher.py` - Amount, merchant, date matching
- `business_classifier.py` - Classification signals and rules
- `smart_notes_service.py` - Note generation logic

### Integration Tests (`@pytest.mark.integration`)
Tests for module interactions. May require database.

```bash
./scripts/run_tests.sh integration
# or
pytest tests/ -m "integration" -v
```

**Coverage:**
- API endpoint responses
- Database operations
- Service integrations

### End-to-End Tests (`@pytest.mark.e2e`)
Full user workflow simulations.

```bash
./scripts/run_tests.sh e2e
# or
pytest tests/ -m "e2e" -v
```

**Coverage:**
- Receipt upload → match → review → report
- Gmail receipt processing flow
- Bulk operations

### Performance Tests (`@pytest.mark.performance`)
Speed and throughput benchmarks.

```bash
./scripts/run_tests.sh performance
# or
pytest tests/ -m "performance" --benchmark-only
```

**Benchmarks:**
- Dashboard load time (<1s for 1000 transactions)
- Matching throughput (100 receipts in <5s)
- OCR processing (<3s per receipt)

### Data Quality Tests (`@pytest.mark.data_quality`)
Matching and classification accuracy.

```bash
./scripts/run_tests.sh data
# or
pytest tests/ -m "data_quality" -v
```

**Targets:**
- Matching accuracy: 95%+
- False positive rate: <2%
- Classification accuracy: 98%+

## Railway Deployment Tests

Tests specific to Railway environments:

```bash
./scripts/run_tests.sh railway
# or
pytest tests/test_railway_deployment.py -v
```

**Coverage:**
- Environment detection (dev/prod)
- Database read-only mode in development
- Health check endpoints
- Custom domain routing (tallyups.com)
- SSL certificate validation

## Environment Configuration

### Local Testing
```bash
export RAILWAY_ENVIRONMENT=test
export DB_READ_ONLY=true
pytest tests/ -m "unit"
```

### Against Development
```bash
export TEST_ENV=development
pytest tests/test_railway_deployment.py -k "Development"
```

### Against Production
```bash
export TEST_ENV=production
pytest tests/test_railway_deployment.py -k "Production"
```

## CI/CD Integration

GitHub Actions workflows in `.github/workflows/`:

### `ci.yml` - Main Pipeline
- **Triggers:** Push to `main` or `dev` branches
- **Jobs:**
  - Unit tests (all pushes)
  - Integration tests (with MySQL service)
  - Code coverage
  - Deploy to development (dev branch)
  - Deploy to production (main branch)
  - Smoke tests after deployment

### `scheduled-tests.yml` - Scheduled Tests
- **Triggers:** Daily at 6 AM UTC, manual dispatch
- **Jobs:**
  - Daily smoke tests
  - Weekly performance benchmarks
  - Weekly data quality validation

## Writing New Tests

### Test File Template
```python
#!/usr/bin/env python3
"""
Test Module Name
================
Brief description of what's being tested.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import modules to test
from smart_auto_matcher import normalize_merchant


class TestFeatureName:
    """Test suite for specific feature."""

    @pytest.mark.unit
    def test_basic_functionality(self):
        """Test description."""
        result = normalize_merchant("TEST MERCHANT")
        assert result == "test merchant"

    @pytest.mark.unit
    @pytest.mark.parametrize("input,expected", [
        ("SQ*COFFEE", "coffee"),
        ("PAYPAL*STORE", "store"),
    ])
    def test_parameterized(self, input, expected):
        """Test with multiple inputs."""
        assert normalize_merchant(input) == expected
```

### Using Fixtures
```python
@pytest.fixture
def sample_transaction():
    """Create sample transaction for testing."""
    return {
        '_index': 1,
        'chase_description': 'ANTHROPIC',
        'chase_amount': '20.00',
        'chase_date': '2025-01-15',
    }

def test_with_fixture(sample_transaction):
    """Test using fixture."""
    assert sample_transaction['chase_description'] == 'ANTHROPIC'
```

### Marking Tests
```python
@pytest.mark.unit           # Fast, no deps
@pytest.mark.integration    # Needs DB
@pytest.mark.e2e           # Full flow
@pytest.mark.performance   # Benchmark
@pytest.mark.data_quality  # Accuracy test
@pytest.mark.slow          # Takes >5s
@pytest.mark.requires_db   # Needs MySQL
@pytest.mark.requires_api  # Needs external API
```

## Coverage Goals

| Module | Target | Current |
|--------|--------|---------|
| smart_auto_matcher.py | 95% | - |
| business_classifier.py | 95% | - |
| smart_notes_service.py | 90% | - |
| db_mysql.py | 80% | - |
| viewer_server.py | 75% | - |
| **Overall** | **80%** | - |

Run coverage report:
```bash
./scripts/run_tests.sh coverage
open coverage_html_report/index.html
```

## Troubleshooting

### Tests not discovering
```bash
# Verify pytest can find tests
pytest --collect-only tests/
```

### Import errors
```bash
# Ensure project root is in path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Database connection errors
```bash
# For local testing, use test database
export MYSQL_URL="mysql://root:password@localhost:3306/receiptai_test"
```

### Railway tests failing
```bash
# Check if services are up
curl https://tallyups.com/health
curl https://web-development-c29a.up.railway.app/health
```

## Test Data

Test fixtures are defined in `conftest.py`:
- `TestDataGenerator` - Generate realistic test data
- `TestTransaction` - Sample transaction structure
- `TestReceipt` - Sample receipt structure

Example merchants for each business type:
- **Business:** Anthropic, OpenAI, Midjourney, GitHub
- **MCR:** Bridgestone Arena, PBR, Justin Boots
- **Personal:** Netflix, Disney+, Kroger, Target
