#!/bin/bash
# Test script for Issue #46: Verify all Slack messages are logged to dashboard

echo "🧪 Testing Issue #46: Complete Slack Message Logging"
echo "=================================================="
echo ""

# Test will verify that ALL messages in an automation workflow are logged:
# 1. User request
# 2. Bot processing message
# 3. Approval request creation
# 4. IT approval decision
# 5. Completion message

echo "📋 Test Steps:"
echo "1. Send SSO request in Slack: 'add me to the clickup sso'"
echo "2. Wait for IT approval request in #privategroup channel"
echo "3. Click 'Approve' button"
echo "4. Check dashboard for complete conversation history"
echo ""

echo "✅ Expected Results:"
echo "   - User message: 'add me to the clickup sso' → LOGGED"
echo "   - Bot message: '✅ Your sso group request is being processed...' → LOGGED"
echo "   - Approval created: '🚨 IT approval request created for SSO_GROUP' → LOGGED"
echo "   - IT decision: '✅ IT approved your request' → LOGGED"
echo "   - Completion: '✅ Request completed! You now have access to...' → LOGGED"
echo ""

echo "🔍 To verify:"
echo "1. Open dashboard: https://s3.amazonaws.com/brie-it-helpdesk-dashboard/index.html"
echo "2. Find the most recent interaction"
echo "3. Click to view conversation history"
echo "4. Verify ALL 5 messages appear in the conversation"
echo ""

echo "📊 Check DynamoDB directly:"
echo "aws dynamodb scan --table-name brie-it-helpdesk-bot-interactions --profile AWSCorp --region us-east-1 --limit 1 --query 'Items[0].conversation_history' | jq -r '.S' | jq"
echo ""

echo "🚀 Deployment Status:"
aws lambda get-function --function-name it-approval-system --profile AWSCorp --region us-east-1 --query 'Configuration.LastModified' --output text
aws lambda get-function --function-name it-helpdesk-bot --profile AWSCorp --region us-east-1 --query 'Configuration.LastModified' --output text
echo ""

echo "✅ Fix deployed and ready for testing!"
