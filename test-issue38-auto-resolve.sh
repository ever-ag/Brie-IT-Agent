#!/bin/bash

# Test Script for GitHub Issue #38: Auto-resolved conversations bypass resumption logic
# Tests the fix for auto-resolved conversation resumption

echo "🧪 Testing Issue #38: Auto-resolved conversation resumption"
echo "=========================================================="

# Configuration
TEST_USER_ID="U02CKQJKJ"  # Test user ID (replace with actual)
LAMBDA_FUNCTION="it-helpdesk-bot"
AWS_PROFILE="AWSCorp"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Step 1: Create initial conversation${NC}"
echo "Please send a test message to the bot in Slack now..."
echo "Example: 'I need help with my printer'"
echo -e "${YELLOW}Press Enter when you've sent the message...${NC}"
read -r

echo -e "${BLUE}Step 2: Trigger auto-resolve manually${NC}"
echo "Triggering auto-resolve via Lambda function..."

# Create auto-resolve event payload
cat > /tmp/auto_resolve_event.json << EOF
{
  "auto_resolve_check": true
}
EOF

# Invoke Lambda to trigger auto-resolve
aws lambda invoke \
  --profile $AWS_PROFILE \
  --function-name $LAMBDA_FUNCTION \
  --payload file:///tmp/auto_resolve_event.json \
  --region us-east-1 \
  /tmp/auto_resolve_response.json

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Auto-resolve triggered successfully${NC}"
else
    echo -e "${RED}❌ Failed to trigger auto-resolve${NC}"
    exit 1
fi

echo -e "${BLUE}Step 3: Wait for auto-resolve to process${NC}"
echo "Waiting 10 seconds for auto-resolve to complete..."
sleep 10

echo -e "${BLUE}Step 4: Test resumption logic${NC}"
echo "Now send a follow-up message to the bot in Slack..."
echo "Example: 'thanks for the help' or 'still having issues'"
echo ""
echo -e "${YELLOW}Expected behavior after the fix:${NC}"
echo "✅ Bot should show 'Welcome back!' prompt"
echo "✅ Bot should display 'Yes, same issue' and 'No, different issue' buttons"
echo "✅ User can choose to resume or start fresh"
echo ""
echo -e "${RED}Old buggy behavior (should NOT happen):${NC}"
echo "❌ Bot automatically responds 'User confirmed issue resolved'"
echo "❌ No resumption prompt shown"
echo ""
echo -e "${YELLOW}Press Enter when you've sent the follow-up message...${NC}"
read -r

echo -e "${BLUE}Step 5: Check Lambda logs${NC}"
echo "Checking recent Lambda logs for debug information..."

# Get recent log events
aws logs filter-log-events \
  --profile $AWS_PROFILE \
  --log-group-name "/aws/lambda/$LAMBDA_FUNCTION" \
  --start-time $(date -d '5 minutes ago' +%s)000 \
  --region us-east-1 \
  --query 'events[?contains(message, `DEBUG`) || contains(message, `Found recent auto-resolved`) || contains(message, `resumption`)].message' \
  --output text

echo ""
echo -e "${BLUE}Step 6: Verify DynamoDB conversation state${NC}"
echo "Checking conversation records in DynamoDB..."

# Scan for recent conversations for the test user
aws dynamodb scan \
  --profile $AWS_PROFILE \
  --table-name brie-it-helpdesk-bot-interactions \
  --filter-expression "user_id = :uid AND #ts > :recent" \
  --expression-attribute-names '{"#ts": "timestamp"}' \
  --expression-attribute-values "{\":uid\": {\"S\": \"$TEST_USER_ID\"}, \":recent\": {\"N\": \"$(date -d '1 hour ago' +%s)\"}}" \
  --query 'Items[*].{InteractionId:interaction_id.S,Timestamp:timestamp.N,Outcome:outcome.S,Description:description.S}' \
  --output table \
  --region us-east-1

echo ""
echo -e "${GREEN}🎯 Test Summary${NC}"
echo "==============="
echo "1. ✅ Initial conversation created"
echo "2. ✅ Auto-resolve triggered manually"
echo "3. ✅ Follow-up message sent"
echo "4. ✅ Logs checked for debug info"
echo "5. ✅ DynamoDB state verified"
echo ""
echo -e "${YELLOW}Manual verification required:${NC}"
echo "- Did the bot show resumption prompt after follow-up message?"
echo "- Were 'Yes, same issue' and 'No, different issue' buttons displayed?"
echo "- Was the conversation NOT automatically marked as resolved?"
echo ""
echo -e "${BLUE}If the fix is working correctly, you should see:${NC}"
echo "✅ 'DEBUG: Found recent auto-resolved conversation for resumption' in logs"
echo "✅ Resumption prompt with buttons in Slack"
echo "✅ User control over conversation flow"

# Cleanup
rm -f /tmp/auto_resolve_event.json /tmp/auto_resolve_response.json

echo ""
echo "🧪 Test completed! Check Slack for the resumption prompt."
