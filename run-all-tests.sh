#!/bin/bash

# Brie IT Agent - Unified Test Suite
# Runs all automated tests and reports manual test status

echo "=========================================="
echo "Brie IT Agent - Complete Test Suite"
echo "=========================================="
echo "Date: $(date)"
echo ""

# Run automated tests
echo "Running automated tests..."
./run-automated-tests.sh

AUTOMATED_EXIT=$?

echo ""
echo "=========================================="
echo "Manual Tests Status"
echo "=========================================="
echo ""
echo "The following tests require manual execution in Slack:"
echo ""
echo "TS001: Distribution List Approvals"
echo "  - TS001-T001: Send 'Add me to the LocalEmployees dl'"
echo "  - TS001-T002: Click Approve button"
echo "  - TS001-T003: Send 'Add me to the employees dl'"
echo ""
echo "TS002: SSO Group Requests"
echo "  - TS002-T001: Send 'add me to the clickup sso'"
echo "  - TS002-T002: Click Approve button"
echo ""
echo "TS005: Conversation History & Timestamps"
echo "  - Verify dashboard displays correct timestamps"
echo ""
echo "TS007: Confluence Search"
echo "  - Send 'How do I reset my password?'"
echo "  - Verify Confluence KB search works"
echo ""
echo "TS009: Smart Conversation Linking"
echo "  - Create timeout conversation about 'Excel is slow'"
echo "  - Send 'Excel still slow' within 24 hours"
echo "  - Verify resumption prompt appears"
echo "  - Test both Yes and No responses"
echo ""
echo "TS010: Response Quality"
echo "  - Manual review of AI responses"
echo "  - Verify accuracy and helpfulness"
echo ""

echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Automated Tests: $([ $AUTOMATED_EXIT -eq 0 ] && echo '✓ PASSED' || echo '✗ FAILED')"
echo "Manual Tests: See list above"
echo ""

exit $AUTOMATED_EXIT
