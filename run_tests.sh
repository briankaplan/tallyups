#!/bin/bash
# ReceiptAI Test Runner
# =====================
# Comprehensive test execution script with virtual environment support

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  ReceiptAI Test Suite Runner${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Parse arguments
TEST_TYPE=${1:-"all"}
VERBOSE=${2:-"-v"}

# Setup virtual environment
setup_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        python3 -m venv "$VENV_DIR"
    fi

    # Activate virtual environment
    source "$VENV_DIR/bin/activate"
}

# Install test dependencies
install_deps() {
    setup_venv
    echo -e "${YELLOW}Installing test dependencies...${NC}"
    pip install --upgrade pip
    pip install -r tests/requirements-test.txt
    echo -e "${GREEN}Dependencies installed successfully!${NC}"
}

# Ensure venv is active and has pytest
ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}Virtual environment not found. Creating and installing dependencies...${NC}"
        install_deps
    else
        source "$VENV_DIR/bin/activate"
        # Check if pytest is installed
        if ! python -c "import pytest" 2>/dev/null; then
            echo -e "${YELLOW}pytest not found. Installing dependencies...${NC}"
            install_deps
        fi
    fi
}

# Run unit tests
run_unit_tests() {
    ensure_venv
    echo -e "${BLUE}Running Unit Tests...${NC}"
    python -m pytest tests/test_unit_*.py \
        $VERBOSE \
        --tb=short \
        --timeout=60 \
        --ignore=tests/test_e2e.py \
        --ignore=tests/test_performance.py \
        --ignore=tests/test_integration.py \
        --ignore=tests/test_data_quality.py \
        2>/dev/null || python -m pytest tests/test_unit_*.py $VERBOSE --tb=short
}

# Run integration tests
run_integration_tests() {
    ensure_venv
    echo -e "${BLUE}Running Integration Tests...${NC}"
    python -m pytest tests/test_integration.py \
        $VERBOSE \
        --tb=short \
        --timeout=120
}

# Run data quality tests
run_data_quality_tests() {
    ensure_venv
    echo -e "${BLUE}Running Data Quality Tests...${NC}"
    python -m pytest tests/test_data_quality.py \
        $VERBOSE \
        --tb=short \
        --timeout=120
}

# Run performance tests
run_performance_tests() {
    ensure_venv
    echo -e "${BLUE}Running Performance Tests...${NC}"
    python -m pytest tests/test_performance.py \
        $VERBOSE \
        --tb=short \
        --timeout=600
}

# Run E2E tests
run_e2e_tests() {
    ensure_venv
    echo -e "${BLUE}Running End-to-End Tests...${NC}"
    python -m pytest tests/test_e2e.py \
        $VERBOSE \
        --tb=short \
        --timeout=300
}

# Run all tests with coverage
run_all_with_coverage() {
    ensure_venv
    echo -e "${BLUE}Running All Tests with Coverage...${NC}"
    python -m pytest tests/ \
        $VERBOSE \
        --tb=short \
        --cov=. \
        --cov-report=html \
        --cov-report=term-missing \
        --cov-fail-under=60 \
        --timeout=300 \
        --ignore=tests/__pycache__
}

# Run quick tests (unit only, fast)
run_quick() {
    ensure_venv
    echo -e "${BLUE}Running Quick Tests (Unit Only)...${NC}"
    python -m pytest tests/test_unit_*.py \
        $VERBOSE \
        --tb=line \
        -x \
        --timeout=30
}

# Main execution
case $TEST_TYPE in
    "unit")
        run_unit_tests
        ;;
    "integration")
        run_integration_tests
        ;;
    "data-quality"|"quality")
        run_data_quality_tests
        ;;
    "performance"|"perf")
        run_performance_tests
        ;;
    "e2e")
        run_e2e_tests
        ;;
    "quick")
        run_quick
        ;;
    "all")
        run_unit_tests
        echo ""
        run_integration_tests
        echo ""
        run_data_quality_tests
        ;;
    "full")
        run_all_with_coverage
        ;;
    "install")
        install_deps
        ;;
    "clean")
        echo -e "${YELLOW}Removing virtual environment...${NC}"
        rm -rf "$VENV_DIR"
        echo -e "${GREEN}Virtual environment removed.${NC}"
        ;;
    *)
        echo -e "${RED}Unknown test type: $TEST_TYPE${NC}"
        echo ""
        echo "Usage: ./run_tests.sh [type] [verbosity]"
        echo ""
        echo "Types:"
        echo "  unit         - Run unit tests only"
        echo "  integration  - Run integration tests"
        echo "  data-quality - Run data quality tests"
        echo "  performance  - Run performance tests"
        echo "  e2e          - Run end-to-end tests"
        echo "  quick        - Run quick unit tests (fail fast)"
        echo "  all          - Run unit + integration + data quality"
        echo "  full         - Run all tests with coverage report"
        echo "  install      - Install test dependencies"
        echo "  clean        - Remove virtual environment"
        echo ""
        echo "Verbosity:"
        echo "  -v   - Verbose (default)"
        echo "  -vv  - Very verbose"
        echo "  -q   - Quiet"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Tests Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
