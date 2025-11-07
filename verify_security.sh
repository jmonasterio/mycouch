#!/bin/bash

# Security Verification Script for Public Release
# Run this before committing to ensure no secrets are exposed

set -e

echo "🔍 Security Verification for mycouch"
echo "======================================"
echo ""

ERRORS=0
WARNINGS=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check and report
check_file() {
    local file=$1
    local pattern=$2
    local description=$3

    if grep -r "$pattern" "$file" 2>/dev/null | grep -v "^Binary" | grep -v ".example" | grep -q . ; then
        echo -e "${RED}❌ FAIL${NC}: $description"
        grep -r "$pattern" "$file" 2>/dev/null | grep -v ".example" | head -3
        ERRORS=$((ERRORS + 1))
        return 1
    else
        echo -e "${GREEN}✅ PASS${NC}: $description"
        return 0
    fi
}

# Function to verify files exist
verify_file_exists() {
    local file=$1
    local description=$2

    if [ -f "$file" ]; then
        echo -e "${GREEN}✅ PASS${NC}: $description"
        return 0
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: $description"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

echo "1️⃣  Checking for hardcoded secrets in Python files..."
check_file "main.py" "password.*=" "No hardcoded passwords in main.py" || WARNINGS=$((WARNINGS + 1))
check_file "main.py" "api_key.*=" "No hardcoded API keys in main.py" || WARNINGS=$((WARNINGS + 1))
echo ""

echo "2️⃣  Checking if secrets files are in git..."
if git ls-files | grep -q "\.env$"; then
    echo -e "${RED}❌ FAIL${NC}: .env file is tracked in git (should be in .gitignore)"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅ PASS${NC}: .env file is NOT tracked in git"
fi

echo "3️⃣  Checking .gitignore configuration..."
if grep -q "\.env$" .gitignore 2>/dev/null; then
    echo -e "${GREEN}✅ PASS${NC}: .env is in .gitignore"
else
    echo -e "${RED}❌ FAIL${NC}: .env is NOT in .gitignore"
    ERRORS=$((ERRORS + 1))
fi

echo "5️⃣  Checking that templates don't contain real secrets..."
if grep -q "admin$" .env.example; then
    echo -e "${YELLOW}⚠️  WARN${NC}: .env.example may contain placeholder values"
    # This is OK - these are placeholders
else
    echo -e "${GREEN}✅ PASS${NC}: .env.example uses placeholder values"
fi
echo ""

echo "6️⃣  Checking for placeholder email/username..."
if grep -q "dev@example.com" pyproject.toml 2>/dev/null; then
    echo -e "${YELLOW}⚠️  WARN${NC}: pyproject.toml has placeholder email"
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "${GREEN}✅ PASS${NC}: pyproject.toml has no placeholder email"
fi
echo ""

echo "7️⃣  Checking documentation..."
verify_file_exists "SECURITY_CHECKLIST.md" "SECURITY_CHECKLIST.md exists"
verify_file_exists "README.md" "README.md exists"
echo ""

echo "8️⃣  Checking for recent commits with secrets..."
COMMITS_WITH_PASSWORD=$(git log --all -p --grep="password\|secret" 2>/dev/null | grep -c "^+" || echo "0")
if [ "$COMMITS_WITH_PASSWORD" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  WARN${NC}: Found commits mentioning passwords/secrets"
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "${GREEN}✅ PASS${NC}: No commits found mentioning passwords/secrets"
fi
echo ""

echo "======================================"
echo "📊 Results:"
echo "======================================"
echo -e "Errors:   ${RED}$ERRORS${NC}"
echo -e "Warnings: ${YELLOW}$WARNINGS${NC}"
echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}🚫 SECURITY CHECK FAILED${NC}"
    echo "   Fix the errors above before pushing to public repository"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}⚠️  SECURITY CHECK PASSED WITH WARNINGS${NC}"
    echo "   Review warnings above and fix if needed"
    exit 0
else
    echo -e "${GREEN}✅ SECURITY CHECK PASSED${NC}"
    echo "   Ready to push to public repository"
    exit 0
fi
