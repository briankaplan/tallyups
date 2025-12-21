#!/bin/bash
# UI Smoke Test Script for Tallyups
# Tests that critical pages and resources load correctly

set -e

BASE_URL="${1:-http://localhost:5050}"
FAILED=0
PASSED=0

echo "========================================"
echo "Tallyups UI Smoke Test"
echo "Base URL: $BASE_URL"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_url() {
    local url="$1"
    local name="$2"
    local expected_code="${3:-200}"

    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")

    if [ "$http_code" = "$expected_code" ]; then
        echo -e "${GREEN}[PASS]${NC} $name ($url) - HTTP $http_code"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $name ($url) - Expected HTTP $expected_code, got $http_code"
        ((FAILED++))
        return 1
    fi
}

test_content() {
    local url="$1"
    local name="$2"
    local pattern="$3"

    content=$(curl -s --max-time 10 "$url" 2>/dev/null || echo "")

    if echo "$content" | grep -q "$pattern"; then
        echo -e "${GREEN}[PASS]${NC} $name - Contains expected content"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $name - Missing expected content: $pattern"
        ((FAILED++))
        return 1
    fi
}

echo "=== Testing Static Resources ==="
test_url "$BASE_URL/static/css/design-system.css" "Design System CSS"
test_url "$BASE_URL/static/js/design-system.js" "Design System JS"
test_url "$BASE_URL/static/js/app-shell.js" "App Shell JS"
test_url "$BASE_URL/static/tallyups-design.css" "Tallyups Design CSS"
echo ""

echo "=== Testing Main Pages ==="
test_url "$BASE_URL/" "Home/Dashboard"
test_url "$BASE_URL/viewer" "Reconciler Viewer"
test_url "$BASE_URL/library" "Receipt Library"
test_url "$BASE_URL/incoming" "Incoming Receipts"
test_url "$BASE_URL/settings" "Settings"
test_url "$BASE_URL/reports" "Reports"
echo ""

echo "=== Testing API Endpoints ==="
test_url "$BASE_URL/api/receipts" "Receipts API" "200"
test_url "$BASE_URL/api/stats" "Stats API" "200"
test_url "$BASE_URL/health" "Health Check" "200"
echo ""

echo "=== Testing Page Content ==="
test_content "$BASE_URL/" "Dashboard has design-system" "design-system"
test_content "$BASE_URL/settings" "Settings has app-shell" "app-shell"
test_content "$BASE_URL/library" "Library has design-system" "design-system"
echo ""

echo "=== Testing No Duplicate CSS Imports ==="
for page in "/" "/viewer" "/library" "/settings" "/incoming"; do
    content=$(curl -s --max-time 10 "$BASE_URL$page" 2>/dev/null || echo "")
    css_count=$(echo "$content" | grep -c "design-system.css" || echo "0")
    if [ "$css_count" -le 1 ]; then
        echo -e "${GREEN}[PASS]${NC} $page - No duplicate design-system.css imports ($css_count found)"
        ((PASSED++))
    else
        echo -e "${RED}[FAIL]${NC} $page - Duplicate design-system.css imports found ($css_count)"
        ((FAILED++))
    fi
done
echo ""

echo "========================================"
echo "Results: $PASSED passed, $FAILED failed"
echo "========================================"

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
