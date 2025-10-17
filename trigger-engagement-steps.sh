#!/bin/bash

# Script to manually trigger engagement steps for testing
# Usage: ./trigger-engagement-steps.sh <interaction_id> <timestamp> <user_id>

INTERACTION_ID="2d883d5c-6d3e-4872-8f8b-07753b4a36ef"
TIMESTAMP="1760707011"
USER_ID="UDR6PV7DX"

echo "🧪 Testing Engagement Workflow for Issue #38"
echo "============================================="
echo "Conversation: $INTERACTION_ID"
echo "User: $USER_ID"
echo ""

# Step 1: Trigger 5-minute engagement
echo "⏰ Step 1: Triggering 5-minute engagement prompt..."
aws lambda invoke --profile AWSCorp --function-name it-helpdesk-bot \
  --payload "{\"engagement_prompt\": true, \"interaction_id\": \"$INTERACTION_ID\", \"timestamp\": $TIMESTAMP, \"user_id\": \"$USER_ID\", \"prompt_number\": 1}" \
  --region us-east-1 /tmp/engagement1_response.json

echo "✅ 5-minute engagement triggered"
echo "Expected: Bot should ask 'Still working on this?' with buttons"
echo ""
read -p "Press Enter when you see the 5-minute prompt in Slack..."

# Step 2: Trigger 10-minute engagement  
echo "⏰ Step 2: Triggering 10-minute engagement prompt..."
aws lambda invoke --profile AWSCorp --function-name it-helpdesk-bot \
  --payload "{\"engagement_prompt\": true, \"interaction_id\": \"$INTERACTION_ID\", \"timestamp\": $TIMESTAMP, \"user_id\": \"$USER_ID\", \"prompt_number\": 2}" \
  --region us-east-1 /tmp/engagement2_response.json

echo "✅ 10-minute engagement triggered"
echo "Expected: Bot should ask again with buttons"
echo ""
read -p "Press Enter when you see the 10-minute prompt in Slack..."

# Step 3: Trigger auto-resolve
echo "⏰ Step 3: Triggering auto-resolve (15 minutes)..."
aws dynamodb update-item --profile AWSCorp \
  --table-name brie-it-helpdesk-bot-interactions \
  --key "{\"interaction_id\": {\"S\": \"$INTERACTION_ID\"}, \"timestamp\": {\"N\": \"$TIMESTAMP\"}}" \
  --update-expression "SET outcome = :outcome, conversation_history = :hist" \
  --expression-attribute-values "{\":outcome\": {\"S\": \"Timed Out - No Response\"}, \":hist\": {\"S\": \"[{\\\"timestamp\\\": \\\"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\\\", \\\"message\\\": \\\"Auto-resolved (no response after 15 minutes)\\\", \\\"from\\\": \\\"bot\\\"}]\"}}" \
  --region us-east-1

echo "✅ Auto-resolve completed"
echo "Expected: Bot should send 'I haven't heard back from you, so I'm closing this conversation...'"
echo ""

# Step 4: Test resumption
echo "🎯 Step 4: Ready to test Issue #38 fix!"
echo "Now send your follow-up message in Slack: 'thanks for the help'"
echo ""
echo "Expected with our fix:"
echo "✅ Bot shows 'Welcome back!' prompt"
echo "✅ Shows 'Yes, same issue' and 'No, different issue' buttons"
echo "✅ You can choose how to proceed"
echo ""
echo "Old buggy behavior (should NOT happen):"
echo "❌ Bot automatically says 'User confirmed issue resolved'"
echo ""
echo "Ready for your follow-up message!"
