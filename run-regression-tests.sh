#!/bin/bash

echo "=========================================="
echo "BRIE IT AGENT REGRESSION TEST EXECUTION"
echo "Date: $(date)"
echo "=========================================="
echo ""

# Test Suite 1: Distribution List Approvals
echo "TS001: Distribution List Approvals"
echo "-----------------------------------"
echo "TS001-T001: DL Request - Single Match"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send 'Add me to the LocalEmployees dl' in Slack"
echo ""
echo "TS001-T002: DL Approval - Auto Close"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Click Approve button after TS001-T001"
echo ""
echo "TS001-T003: DL Request - Multiple Matches"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send 'Add me to the employees dl' in Slack"
echo ""

# Test Suite 2: SSO Group Requests
echo "TS002: SSO Group Requests"
echo "-------------------------"
echo "TS002-T001: SSO Group Request"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send 'add me to the clickup sso' in Slack"
echo ""
echo "TS002-T002: SSO Approval - Auto Close"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Approve SSO request after TS002-T001"
echo ""

# Test Suite 3: Shared Mailbox
echo "TS003: Shared Mailbox Requests"
echo "------------------------------"
echo "TS003-T001: Shared Mailbox Request"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send 'Add me to the itsupport@ever.ag shared mailbox' in Slack"
echo ""

# Test Suite 4: RTD Issues
echo "TS004: Application Support - RTD Issues"
echo "---------------------------------------"
echo "TS004-T001: RTD Issue Detection"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send 'I am having RTD issues in Excel' in Slack"
echo ""
echo "TS004-T002: RTD Resolution Confirmation"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Click 'Yes, that worked!' after TS004-T001"
echo ""

# Test Suite 5: Timestamps - Can check DynamoDB
echo "TS005: Conversation History & Timestamps"
echo "----------------------------------------"
echo "TS005-T001: Initial Message Timestamp"
echo "  Checking DynamoDB for timestamp format..."

# Get latest interaction
LATEST=$(aws dynamodb scan \
  --profile AWSCorp \
  --region us-east-1 \
  --table-name brie-it-helpdesk-bot-interactions \
  --limit 1 \
  --output json 2>/dev/null)

if [ $? -eq 0 ]; then
  CONV_HISTORY=$(echo "$LATEST" | jq -r '.Items[0].conversation_history.S' 2>/dev/null)
  
  if echo "$CONV_HISTORY" | jq -e '.[0].timestamp_ms' >/dev/null 2>&1; then
    echo "  Status: ✓ PASS - timestamp_ms field present"
  else
    echo "  Status: ✗ FAIL - timestamp_ms field missing"
  fi
  
  if echo "$CONV_HISTORY" | jq -e '.[0].timestamp' >/dev/null 2>&1; then
    echo "  Status: ✓ PASS - timestamp field present"
  else
    echo "  Status: ✗ FAIL - timestamp field missing"
  fi
else
  echo "  Status: ERROR - Could not query DynamoDB"
fi
echo ""

echo "TS005-T002: Bot Response Timestamp"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Check dashboard for 'Invalid Date'"
echo ""

# Test Suite 6: Interaction Categorization
echo "TS006: Interaction Categorization"
echo "---------------------------------"
echo "TS006-T001 to T005: Categorization Tests"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send various messages and verify interaction_type in DynamoDB"
echo ""

# Test Suite 7: DynamoDB Logging
echo "TS007: DynamoDB Interaction Logging"
echo "-----------------------------------"
echo "TS007-T001: Interaction Logged to DynamoDB"
echo "  Checking required fields in latest interaction..."

if [ $? -eq 0 ]; then
  REQUIRED_FIELDS=("interaction_id" "timestamp" "user_id" "user_name" "interaction_type" "description" "outcome" "conversation_history")
  ALL_PRESENT=true
  
  for field in "${REQUIRED_FIELDS[@]}"; do
    if echo "$LATEST" | jq -e ".Items[0].$field" >/dev/null 2>&1; then
      echo "  ✓ $field present"
    else
      echo "  ✗ $field MISSING"
      ALL_PRESENT=false
    fi
  done
  
  if [ "$ALL_PRESENT" = true ]; then
    echo "  Status: ✓ PASS - All required fields present"
  else
    echo "  Status: ✗ FAIL - Some fields missing"
  fi
else
  echo "  Status: ERROR - Could not query DynamoDB"
fi
echo ""

# Test Suite 8: Confluence
echo "TS008: Confluence Integration"
echo "-----------------------------"
echo "TS008-T001: Confluence Content Retrieval"
echo "  Status: KNOWN ISSUE - Confluence API 403 (Issue #7)"
echo ""
echo "TS008-T002: Confluence Image Upload"
echo "  Status: KNOWN ISSUE - Confluence API 403 (Issue #7)"
echo ""

# Test Suite 9: Ticket Creation
echo "TS009: Ticket Creation"
echo "---------------------"
echo "TS009-T001: Create Ticket from Conversation"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Send message and click 'Create ticket' button"
echo ""

# Test Suite 10: Dashboard
echo "TS010: Dashboard Functionality"
echo "------------------------------"
echo "TS010-T001: Dashboard Loads"
echo "  Testing dashboard accessibility..."

DASHBOARD_URL="https://dyxb7ssm7p469.cloudfront.net/"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$DASHBOARD_URL" 2>/dev/null)

if [ "$HTTP_CODE" = "200" ]; then
  echo "  Status: ✓ PASS - Dashboard loads (HTTP $HTTP_CODE)"
else
  echo "  Status: ✗ FAIL - Dashboard error (HTTP $HTTP_CODE)"
fi
echo ""

echo "TS010-T002: Conversation History Display"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Click on interaction in dashboard"
echo ""

echo "TS010-T003: Filter by Interaction Type"
echo "  Status: MANUAL TEST REQUIRED"
echo "  Action: Use filter dropdown in dashboard"
echo ""

echo "=========================================="
echo "TEST EXECUTION COMPLETE"
echo "=========================================="
echo ""
echo "SUMMARY:"
echo "- Automated checks: Completed"
echo "- Manual tests: Require Slack interaction"
echo "- Known issues: Confluence API 403 (Issue #7)"
echo ""
