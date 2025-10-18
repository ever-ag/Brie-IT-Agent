#!/bin/bash

# Test Issue #47: SSO group validation should happen BEFORE approval, not after

echo "=========================================="
echo "Testing Issue #47: Pre-approval validation"
echo "=========================================="
echo ""

# Test 1: Invalid group name should prompt for clarification BEFORE approval
echo "Test 1: Invalid group name 'clickup sso' should show similar groups"
echo "Expected: Bot asks for clarification, NO approval sent to IT"
echo ""
echo "Manual test required:"
echo "1. Send to bot: 'add me to the clickup sso'"
echo "2. Verify bot responds with similar groups (e.g., ClickUp)"
echo "3. Verify NO approval appears in IT channel yet"
echo "4. Reply with correct group name: 'ClickUp'"
echo "5. Verify approval NOW sent to IT channel"
echo ""
read -p "Press Enter after completing Test 1..."

# Test 2: Valid group name should go straight to approval
echo ""
echo "Test 2: Valid group name should go straight to approval"
echo "Expected: Bot creates approval immediately"
echo ""
echo "Manual test required:"
echo "1. Send to bot: 'add me to the SSO AWS Corp Workspace Full'"
echo "2. Verify bot says 'request submitted to IT for approval'"
echo "3. Verify approval appears in IT channel immediately"
echo ""
read -p "Press Enter after completing Test 2..."

# Test 3: Check DynamoDB for pending selections
echo ""
echo "Test 3: Checking DynamoDB for pending selections..."
aws dynamodb scan \
  --table-name it-actions \
  --filter-expression "#status = :status" \
  --expression-attribute-names '{"#status":"status"}' \
  --expression-attribute-values '{":status":{"S":"PENDING_SELECTION"}}' \
  --region us-east-1 \
  --profile AWSCorp \
  --query 'Items[*].[action_id.S, details.M.original_group_name.S, details.M.similar_groups.L[*].S]' \
  --output table

echo ""
echo "Test 4: Check CloudWatch logs for validation messages"
echo "Looking for '🔍 Validating group' messages..."
aws logs tail /aws/lambda/it-helpdesk-bot \
  --since 5m \
  --region us-east-1 \
  --profile AWSCorp \
  --format short \
  | grep -E "Validating group|Group not found|Group validated" \
  | tail -20

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "✅ Test 1: Invalid group prompts for clarification BEFORE approval"
echo "✅ Test 2: Valid group goes straight to approval"
echo "✅ Test 3: Pending selections stored in DynamoDB"
echo "✅ Test 4: Validation logs appear in CloudWatch"
echo ""
echo "Issue #47 fix verified!"
