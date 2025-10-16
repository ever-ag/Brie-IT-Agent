#!/bin/bash
PROFILE="AWSCorp"
REGION="us-east-1"
LAMBDA_FUNCTION="it-helpdesk-bot"
INTERACTIONS_TABLE="brie-it-helpdesk-bot-interactions"
TEST_USER_ID="UDR6PV7DX"

echo "Running TS024-T003: Shared mailbox failure appears in conversation history"

# Create shared mailbox request that will fail
PAYLOAD=$(cat <<EOF
{
  "event": {
    "type": "message",
    "user": "$TEST_USER_ID",
    "text": "add me to the test-nonexistent-mailbox@ever.ag shared mailbox",
    "channel": "D09C5MFCV47",
    "ts": "$(date +%s).000002"
  }
}
EOF
)

echo "Sending request..."
RESPONSE=$(aws lambda invoke --profile $PROFILE --region $REGION \
    --function-name $LAMBDA_FUNCTION \
    --payload "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    /dev/stdout 2>/dev/null | head -1)

echo "Waiting 10 seconds for approval and execution..."
sleep 10

# Check conversation history for failure message
echo "Checking conversation history..."
HISTORY=$(aws dynamodb scan --profile $PROFILE --region $REGION \
    --table-name $INTERACTIONS_TABLE \
    --filter-expression "user_id = :uid" \
    --expression-attribute-values '{":uid":{"S":"'$TEST_USER_ID'"}}' \
    --query 'Items[0].conversation_history.S' --output text 2>/dev/null || echo "[]")

echo "Conversation history:"
echo "$HISTORY" | jq -r '.' 2>/dev/null || echo "$HISTORY"

if echo "$HISTORY" | grep -q "Request Failed\|Failed to add"; then
    echo "✓ PASS: Failure message added to conversation history"
    exit 0
else
    echo "✗ FAIL: Failure message missing from conversation history"
    exit 1
fi
