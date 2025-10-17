#!/usr/bin/env python3
"""
Automated test for GitHub Issue #38: Auto-resolved conversations bypass resumption logic
This script simulates the entire flow programmatically
"""

import boto3
import json
import time
import uuid
from datetime import datetime, timedelta

# Configuration
AWS_PROFILE = 'AWSCorp'
REGION = 'us-east-1'
LAMBDA_FUNCTION = 'it-helpdesk-bot'
DYNAMODB_TABLE = 'brie-it-helpdesk-bot-interactions'
TEST_USER_ID = 'U_TEST_ISSUE38'
TEST_USER_NAME = 'Test User Issue38'

# Initialize AWS clients
session = boto3.Session(profile_name=AWS_PROFILE)
lambda_client = session.client('lambda', region_name=REGION)
dynamodb = session.resource('dynamodb', region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

def create_test_conversation():
    """Create a test conversation in DynamoDB"""
    interaction_id = str(uuid.uuid4())
    timestamp = int(datetime.utcnow().timestamp())
    
    item = {
        'interaction_id': interaction_id,
        'timestamp': timestamp,
        'user_id': TEST_USER_ID,
        'user_name': TEST_USER_NAME,
        'interaction_type': 'Hardware Request',
        'description': 'I need help with my printer not working',
        'outcome': 'In Progress',
        'date': datetime.utcnow().isoformat(),
        'conversation_history': json.dumps([{
            'timestamp': datetime.utcnow().isoformat(),
            'message': 'I need help with my printer not working',
            'from': 'user'
        }]),
        'metadata': '{}'
    }
    
    table.put_item(Item=item)
    print(f"✅ Created test conversation: {interaction_id}")
    return interaction_id, timestamp

def auto_resolve_conversation(interaction_id, timestamp):
    """Simulate auto-resolve by updating the conversation outcome"""
    try:
        # Update conversation to auto-resolved state
        table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp},
            UpdateExpression='SET outcome = :outcome, conversation_history = :hist',
            ExpressionAttributeValues={
                ':outcome': 'Timed Out - No Response',
                ':hist': json.dumps([
                    {
                        'timestamp': datetime.utcnow().isoformat(),
                        'message': 'I need help with my printer not working',
                        'from': 'user'
                    },
                    {
                        'timestamp': datetime.utcnow().isoformat(),
                        'message': 'Auto-resolved (no response after 15 minutes)',
                        'from': 'bot'
                    }
                ])
            }
        )
        print(f"✅ Auto-resolved conversation: {interaction_id}")
        return True
    except Exception as e:
        print(f"❌ Failed to auto-resolve: {e}")
        return False

def test_resumption_logic():
    """Test the resumption logic by simulating a follow-up message"""
    # Create mock Slack event for follow-up message
    slack_event = {
        'type': 'message',
        'user': TEST_USER_ID,
        'text': 'thanks for the help',
        'channel': 'D_TEST_CHANNEL',
        'ts': str(time.time())
    }
    
    # Create Lambda event payload
    lambda_event = {
        'body': json.dumps({
            'event': slack_event,
            'type': 'event_callback'
        })
    }
    
    try:
        # Invoke Lambda function
        response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION,
            Payload=json.dumps(lambda_event)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"✅ Lambda invocation successful: {result.get('statusCode')}")
        return True
    except Exception as e:
        print(f"❌ Lambda invocation failed: {e}")
        return False

def check_conversation_state(interaction_id, timestamp):
    """Check the final state of the conversation"""
    try:
        response = table.get_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp}
        )
        
        if 'Item' in response:
            item = response['Item']
            print(f"📊 Conversation state:")
            print(f"   - Outcome: {item.get('outcome')}")
            print(f"   - Description: {item.get('description')}")
            return item
        else:
            print("❌ Conversation not found")
            return None
    except Exception as e:
        print(f"❌ Failed to check conversation: {e}")
        return None

def cleanup_test_data(interaction_id, timestamp):
    """Clean up test data"""
    try:
        table.delete_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp}
        )
        print(f"🧹 Cleaned up test conversation: {interaction_id}")
    except Exception as e:
        print(f"⚠️ Failed to cleanup: {e}")

def main():
    print("🧪 Automated Test for Issue #38: Auto-resolved conversation resumption")
    print("=" * 70)
    
    # Step 1: Create test conversation
    print("\n📝 Step 1: Creating test conversation...")
    interaction_id, timestamp = create_test_conversation()
    
    # Step 2: Auto-resolve the conversation
    print("\n⏰ Step 2: Auto-resolving conversation...")
    if not auto_resolve_conversation(interaction_id, timestamp):
        cleanup_test_data(interaction_id, timestamp)
        return
    
    # Step 3: Wait a moment
    print("\n⏳ Step 3: Waiting 2 seconds...")
    time.sleep(2)
    
    # Step 4: Test resumption logic
    print("\n🔄 Step 4: Testing resumption logic...")
    if not test_resumption_logic():
        cleanup_test_data(interaction_id, timestamp)
        return
    
    # Step 5: Check final state
    print("\n📊 Step 5: Checking conversation state...")
    final_state = check_conversation_state(interaction_id, timestamp)
    
    # Step 6: Analyze results
    print("\n🎯 Step 6: Test Results")
    print("-" * 30)
    
    if final_state:
        outcome = final_state.get('outcome')
        if outcome == 'Timed Out - No Response':
            print("✅ PASS: Conversation maintained auto-resolved state")
            print("✅ PASS: Resumption logic should have been triggered")
        elif outcome == 'Self-Service Solution':
            print("❌ FAIL: Conversation was automatically marked as resolved")
            print("❌ FAIL: Resumption logic was bypassed")
        else:
            print(f"⚠️ UNKNOWN: Unexpected outcome: {outcome}")
    
    # Step 7: Cleanup
    print("\n🧹 Step 7: Cleaning up test data...")
    cleanup_test_data(interaction_id, timestamp)
    
    print("\n✅ Test completed!")
    print("\nTo verify the fix is working:")
    print("1. Check Lambda logs for 'DEBUG: Found recent auto-resolved conversation for resumption'")
    print("2. In a real Slack test, you should see resumption prompt with buttons")
    print("3. The conversation should NOT be automatically marked as resolved")

if __name__ == "__main__":
    main()
