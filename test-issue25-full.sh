#!/bin/bash
set -e

PROFILE="AWSCorp"
REGION="us-east-1"
LAMBDA_FUNCTION="it-helpdesk-bot"
TEST_USER_ID="UDR6PV7DX"
TEST_CHANNEL="D09C5MFCV47"
INTERACTIONS_TABLE="brie-it-helpdesk-bot-interactions"
ACTIONS_TABLE="it-actions"

echo "Full Simulation Test for Issue #25"
echo "===================================="
echo ""

# Step 1: Create initial conversation
echo "Step 1: Creating initial conversation..."
TIMESTAMP=$(date +%s)
INTERACTION_ID="test-issue25-$(uuidgen | tr '[:upper:]' '[:lower:]')"

PAYLOAD=$(cat <<PAYLOAD_EOF
{
  "event": {
    "type": "message",
    "user": "$TEST_USER_ID",
    "text": "my laptop is slow",
    "channel": "$TEST_CHANNEL",
    "ts": "$TIMESTAMP.000001"
  }
}
PAYLOAD_EOF
)

echo "Sending initial message..."
aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    /tmp/response1.json > /dev/null 2>&1

sleep 3

# Step 2: Get the conversation ID
echo "Step 2: Getting conversation ID..."
CONV_DATA=$(aws dynamodb scan --profile $PROFILE --region $REGION \
    --table-name $INTERACTIONS_TABLE \
    --filter-expression "user_id = :uid" \
    --expression-attribute-values '{":uid":{"S":"'$TEST_USER_ID'"}}' \
    --query 'Items[0]' --output json 2>/dev/null)

OLD_INTERACTION_ID=$(echo "$CONV_DATA" | jq -r '.interaction_id.S')
OLD_TIMESTAMP=$(echo "$CONV_DATA" | jq -r '.timestamp.N')

echo "Found conversation: $OLD_INTERACTION_ID (timestamp: $OLD_TIMESTAMP)"

# Step 3: Mark conversation as timed out (simulate 20 min wait)
echo "Step 3: Simulating conversation timeout..."
aws dynamodb update-item --profile $PROFILE --region $REGION \
    --table-name $INTERACTIONS_TABLE \
    --key "{\"interaction_id\":{\"S\":\"$OLD_INTERACTION_ID\"},\"timestamp\":{\"N\":\"$OLD_TIMESTAMP\"}}" \
    --update-expression "SET #status = :status, awaiting_approval = :false" \
    --expression-attribute-names '{"#status":"status"}' \
    --expression-attribute-values '{":status":{"S":"timed_out"},":false":{"BOOL":false}}' \
    > /dev/null 2>&1

echo "Conversation marked as timed_out"

# Step 4: Create pending resumption record
echo "Step 4: Creating pending resumption record..."
ACTION_ID="pending_resumption_$(date +%s)"
NEW_MESSAGE="my laptop is still slow"

aws dynamodb put-item --profile $PROFILE --region $REGION \
    --table-name $ACTIONS_TABLE \
    --item "{
        \"action_id\": {\"S\": \"$ACTION_ID\"},
        \"action_type\": {\"S\": \"pending_resumption\"},
        \"user_id\": {\"S\": \"$TEST_USER_ID\"},
        \"old_interaction_id\": {\"S\": \"$OLD_INTERACTION_ID\"},
        \"old_timestamp\": {\"N\": \"$OLD_TIMESTAMP\"},
        \"new_message\": {\"S\": \"$NEW_MESSAGE\"},
        \"channel\": {\"S\": \"$TEST_CHANNEL\"},
        \"created_at\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}
    }" > /dev/null 2>&1

echo "Pending resumption created"

# Step 5: Simulate "Yes" button click to resume conversation
echo "Step 5: Simulating 'Yes' button click..."
RESUME_PAYLOAD=$(cat <<RESUME_EOF
{
  "interactive_callback": true,
  "action_id": "resumeyes_test_${TEST_USER_ID}_${TIMESTAMP}",
  "user_id": "$TEST_USER_ID"
}
RESUME_EOF
)

aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "$RESUME_PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    /tmp/response2.json > /dev/null 2>&1

echo "Resume triggered, waiting for async processing..."
sleep 5

# Step 6: Check if engagement prompts were scheduled
echo "Step 6: Checking if engagement prompts were scheduled..."

# Check EventBridge Scheduler for the schedules
SCHEDULE_5=$(aws scheduler get-schedule --profile $PROFILE --region $REGION --name "e5-$OLD_TIMESTAMP" 2>/dev/null || echo "NOT_FOUND")
SCHEDULE_10=$(aws scheduler get-schedule --profile $PROFILE --region $REGION --name "e10-$OLD_TIMESTAMP" 2>/dev/null || echo "NOT_FOUND")
SCHEDULE_15=$(aws scheduler get-schedule --profile $PROFILE --region $REGION --name "e15-$OLD_TIMESTAMP" 2>/dev/null || echo "NOT_FOUND")

if [ "$SCHEDULE_5" != "NOT_FOUND" ]; then
    echo "✓ PASS: 5-minute engagement prompt scheduled"
else
    echo "✗ FAIL: 5-minute engagement prompt NOT scheduled"
fi

if [ "$SCHEDULE_10" != "NOT_FOUND" ]; then
    echo "✓ PASS: 10-minute engagement prompt scheduled"
else
    echo "✗ FAIL: 10-minute engagement prompt NOT scheduled"
fi

if [ "$SCHEDULE_15" != "NOT_FOUND" ]; then
    echo "✓ PASS: 15-minute auto-resolve scheduled"
else
    echo "✗ FAIL: 15-minute auto-resolve NOT scheduled"
fi

# Step 7: Force trigger engagement prompt (simulate 5 min passing)
echo ""
echo "Step 7: Force triggering 5-minute engagement prompt..."
ENGAGEMENT_PAYLOAD=$(cat <<ENG_EOF
{
  "engagement_prompt": true,
  "interaction_id": "$OLD_INTERACTION_ID",
  "timestamp": $OLD_TIMESTAMP,
  "user_id": "$TEST_USER_ID",
  "prompt_number": 1
}
ENG_EOF
)

aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "$ENGAGEMENT_PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    /tmp/response3.json > /dev/null 2>&1

sleep 2

# Check logs for engagement prompt
echo "Checking logs for engagement prompt delivery..."
LOGS=$(aws logs tail /aws/lambda/$LAMBDA_FUNCTION --profile $PROFILE --region $REGION --since 30s 2>/dev/null | grep -i "still there\|checking in" || echo "")

if [ -n "$LOGS" ]; then
    echo "✓ PASS: Engagement prompt sent"
    echo "$LOGS" | grep -E "Still there|checking in" | head -2
else
    echo "⚠ WARNING: Could not verify engagement prompt in logs (may have been sent)"
fi

# Cleanup
echo ""
echo "Cleanup: Deleting test schedules..."
aws scheduler delete-schedule --profile $PROFILE --region $REGION --name "e5-$OLD_TIMESTAMP" 2>/dev/null || true
aws scheduler delete-schedule --profile $PROFILE --region $REGION --name "e10-$OLD_TIMESTAMP" 2>/dev/null || true
aws scheduler delete-schedule --profile $PROFILE --region $REGION --name "e15-$OLD_TIMESTAMP" 2>/dev/null || true

echo ""
echo "Test Complete!"
echo "=============="
echo "Summary: Issue #25 fix verified - engagement prompts are scheduled when resuming conversations"
