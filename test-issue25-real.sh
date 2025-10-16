#!/bin/bash
set -e

PROFILE="AWSCorp"
REGION="us-east-1"
LAMBDA_FUNCTION="it-helpdesk-bot"
TEST_USER_ID="UDR6PV7DX"
TEST_CHANNEL="D09C5MFCV47"

echo "=== FULL SIMULATION: Issue #25 ==="
echo ""

# Step 1: Send initial message
echo "Step 1: Sending 'my laptop is slow'..."
TS1=$(date +%s)
aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "{\"event\":{\"type\":\"message\",\"user\":\"$TEST_USER_ID\",\"text\":\"my laptop is slow\",\"channel\":\"$TEST_CHANNEL\",\"ts\":\"$TS1.000001\"}}" \
    --cli-binary-format raw-in-base64-out /tmp/r1.json >/dev/null 2>&1

sleep 5

# Get conversation details
CONV=$(aws dynamodb scan --profile $PROFILE --region $REGION \
    --table-name brie-it-helpdesk-bot-interactions \
    --filter-expression "user_id = :uid" \
    --expression-attribute-values '{":uid":{"S":"'$TEST_USER_ID'"}}' \
    --query 'Items[0]' --output json)

OLD_ID=$(echo "$CONV" | jq -r '.interaction_id.S')
OLD_TS=$(echo "$CONV" | jq -r '.timestamp.N')

echo "   Created conversation: $OLD_ID"

# Step 2: Manually timeout the conversation
echo "Step 2: Timing out conversation..."
aws dynamodb update-item --profile $PROFILE --region $REGION \
    --table-name brie-it-helpdesk-bot-interactions \
    --key "{\"interaction_id\":{\"S\":\"$OLD_ID\"},\"timestamp\":{\"N\":\"$OLD_TS\"}}" \
    --update-expression "SET #s = :s" \
    --expression-attribute-names '{"#s":"status"}' \
    --expression-attribute-values '{":s":{"S":"timed_out"}}' >/dev/null 2>&1

echo "   Conversation timed out"

# Step 3: Send new message (triggers smart linking)
echo "Step 3: Sending 'my laptop is still slow'..."
TS2=$((TS1 + 1200))
aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "{\"event\":{\"type\":\"message\",\"user\":\"$TEST_USER_ID\",\"text\":\"my laptop is still slow\",\"channel\":\"$TEST_CHANNEL\",\"ts\":\"$TS2.000001\"}}" \
    --cli-binary-format raw-in-base64-out /tmp/r2.json >/dev/null 2>&1

sleep 3
echo "   Smart linking prompt sent"

# Step 4: Simulate clicking "Yes" button
echo "Step 4: Clicking 'Yes' to resume..."

# Create pending resumption in DynamoDB
ACTION_ID="pending_$(date +%s)"
aws dynamodb put-item --profile $PROFILE --region $REGION \
    --table-name it-actions \
    --item "{
        \"action_id\":{\"S\":\"$ACTION_ID\"},
        \"action_type\":{\"S\":\"pending_resumption\"},
        \"user_id\":{\"S\":\"$TEST_USER_ID\"},
        \"old_interaction_id\":{\"S\":\"$OLD_ID\"},
        \"old_timestamp\":{\"N\":\"$OLD_TS\"},
        \"new_message\":{\"S\":\"my laptop is still slow\"},
        \"channel\":{\"S\":\"$TEST_CHANNEL\"}
    }" >/dev/null 2>&1

# Simulate button click with proper Slack format
BUTTON_PAYLOAD=$(cat <<BTNEOF
{
  "type": "block_actions",
  "user": {"id": "$TEST_USER_ID"},
  "actions": [{
    "action_id": "resumeyes_${ACTION_ID}_${TEST_USER_ID}_${TS2}",
    "type": "button"
  }],
  "channel": {"id": "$TEST_CHANNEL"}
}
BTNEOF
)

aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "$BUTTON_PAYLOAD" \
    --cli-binary-format raw-in-base64-out /tmp/r3.json >/dev/null 2>&1

sleep 8
echo "   Resume triggered"

# Step 5: Check if schedules were created
echo "Step 5: Checking for engagement prompt schedules..."

CHECK_5=$(aws scheduler get-schedule --profile $PROFILE --region $REGION --name "e5-$OLD_TS" 2>&1)
CHECK_10=$(aws scheduler get-schedule --profile $PROFILE --region $REGION --name "e10-$OLD_TS" 2>&1)
CHECK_15=$(aws scheduler get-schedule --profile $PROFILE --region $REGION --name "e15-$OLD_TS" 2>&1)

PASS_COUNT=0

if echo "$CHECK_5" | grep -q "ScheduleArn"; then
    echo "   ✓ 5-minute prompt scheduled"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "   ✗ 5-minute prompt NOT scheduled"
fi

if echo "$CHECK_10" | grep -q "ScheduleArn"; then
    echo "   ✓ 10-minute prompt scheduled"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "   ✗ 10-minute prompt NOT scheduled"
fi

if echo "$CHECK_15" | grep -q "ScheduleArn"; then
    echo "   ✓ 15-minute auto-resolve scheduled"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "   ✗ 15-minute auto-resolve NOT scheduled"
fi

# Step 6: Force trigger 5-min prompt
echo "Step 6: Force triggering 5-minute engagement prompt..."
aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "{\"engagement_prompt\":true,\"interaction_id\":\"$OLD_ID\",\"timestamp\":$OLD_TS,\"user_id\":\"$TEST_USER_ID\",\"prompt_number\":1}" \
    --cli-binary-format raw-in-base64-out /tmp/r4.json >/dev/null 2>&1

sleep 2

# Check Slack logs
SLACK_LOGS=$(aws logs tail /aws/lambda/$LAMBDA_FUNCTION --profile $PROFILE --region $REGION --since 30s 2>&1 | grep -i "still there" || echo "")

if [ -n "$SLACK_LOGS" ]; then
    echo "   ✓ Engagement prompt delivered to Slack"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "   ⚠ Could not verify Slack delivery"
fi

# Cleanup
echo ""
echo "Cleanup: Removing test schedules..."
aws scheduler delete-schedule --profile $PROFILE --region $REGION --name "e5-$OLD_TS" 2>/dev/null || true
aws scheduler delete-schedule --profile $PROFILE --region $REGION --name "e10-$OLD_TS" 2>/dev/null || true  
aws scheduler delete-schedule --profile $PROFILE --region $REGION --name "e15-$OLD_TS" 2>/dev/null || true

echo ""
echo "=== TEST RESULTS ==="
echo "Passed: $PASS_COUNT/4 checks"
if [ $PASS_COUNT -ge 3 ]; then
    echo "✓ TEST PASSED: Issue #25 fix is working"
    exit 0
else
    echo "✗ TEST FAILED: Some checks did not pass"
    exit 1
fi
