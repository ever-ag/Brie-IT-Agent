#!/bin/bash

echo "Issue #25 Verification Test"
echo "============================"
echo ""
echo "Verifying fix is deployed..."
echo ""

# Check the deployed Lambda code has the fix
echo "1. Checking deployed Lambda code..."
aws lambda get-function --function-name it-helpdesk-bot --region us-east-1 --profile AWSCorp \
  --query 'Code.Location' --output text | \
  xargs curl -s -o /tmp/deployed-lambda.zip

unzip -q -o /tmp/deployed-lambda.zip -d /tmp/deployed-lambda/
OCCURRENCES=$(grep -c "schedule_auto_resolve(old_interaction_id" /tmp/deployed-lambda/lambda_it_bot_confluence.py 2>/dev/null || echo "0")

if [ "$OCCURRENCES" -ge 2 ]; then
    echo "   ✓ PASS: Fix is deployed ($OCCURRENCES occurrences found)"
else
    echo "   ✗ FAIL: Fix not found in deployed code"
    exit 1
fi

# Check local code
echo "2. Checking local code..."
LOCAL_OCCURRENCES=$(grep -c "schedule_auto_resolve(old_interaction_id" ~/Brie-IT-Agent/lambda_it_bot_confluence.py)
if [ "$LOCAL_OCCURRENCES" -ge 2 ]; then
    echo "   ✓ PASS: Fix is in local code ($LOCAL_OCCURRENCES occurrences)"
else
    echo "   ✗ FAIL: Fix not in local code"
    exit 1
fi

# Show the exact lines
echo ""
echo "3. Fix locations:"
grep -n "schedule_auto_resolve(old_interaction_id" ~/Brie-IT-Agent/lambda_it_bot_confluence.py

echo ""
echo "✓ Issue #25 fix verified in both local and deployed code"
echo ""
echo "Manual test to confirm behavior:"
echo "1. Send: 'my laptop is slow'"
echo "2. Wait 20 minutes"
echo "3. Send: 'my laptop is still slow'"
echo "4. Click 'Yes' to resume"
echo "5. Wait and verify engagement prompts arrive at 5min, 10min, 15min"

rm -rf /tmp/deployed-lambda /tmp/deployed-lambda.zip
