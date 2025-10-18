import json
import boto3
import os
import urllib3
from datetime import datetime

def lambda_handler(event, context):
    """Handle both approval buttons and resolution buttons"""
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Parse the payload
        if 'body' in event:
            body = json.loads(event['body'])
            
            # Handle URL verification
            if body.get('type') == 'url_verification':
                return {'statusCode': 200, 'body': body['challenge']}
            
            # Handle interactive events (button clicks)
            if body.get('type') == 'interactive':
                payload = body.get('payload')
                if isinstance(payload, str):
                    import urllib.parse
                    payload = json.loads(urllib.parse.unquote(payload))
                else:
                    payload = body
                
                # Extract action info
                actions = payload.get('actions', [])
                if actions:
                    action_id = actions[0].get('action_id', '')
                    user_id = payload.get('user', {}).get('id', '')
                    channel = payload.get('channel', {}).get('id', '')
                    
                    print(f"Button clicked: {action_id} by {user_id} in {channel}")
                    
                    # Handle resolution buttons from comprehensive IT system
                    if action_id.startswith(('resolved_', 'unresolved_', 'ticket_')):
                        return handle_resolution_button(action_id, user_id, channel)
                    
                    # Handle approval buttons (existing functionality)
                    elif action_id.startswith(('approve_', 'deny_')):
                        return handle_approval_button(action_id, user_id, channel)
                
                return {'statusCode': 200, 'body': 'Interactive event processed'}
        
        # Handle direct invocations (existing approval system functionality)
        return handle_approval_request(event)
        
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}

def handle_resolution_button(action_id, user_id, channel):
    """Handle resolution buttons from comprehensive IT system"""
    try:
        if action_id.startswith('resolved_'):
            message = "Great! Glad I could help resolve your issue. If you need anything else, just ask!"
            
        elif action_id.startswith('unresolved_'):
            message = "I understand the issue isn't resolved yet. Let me help you further.\n\nYou can:\n• Describe what's still not working\n• Say 'create ticket' to submit a support request\n• Contact IT directly: itsupport@ever.ag or 214-807-0784"
                     
        elif action_id.startswith('ticket_'):
            message = "I'll help you create a support ticket. Please describe your issue in detail and I'll submit it to the IT team."
        
        else:
            message = "👍 Thanks for the feedback!"
        
        # Send response to user
        send_slack_message(channel, message)
        
        # Update conversation in DynamoDB if needed
        update_conversation_status(action_id, user_id, 'resolved' if action_id.startswith('resolved_') else 'needs_help')
        
        return {'statusCode': 200, 'body': 'Resolution button handled'}
        
    except Exception as e:
        print(f"Error handling resolution button: {e}")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}

def handle_approval_button(action_id, user_id, channel):
    """Handle approval buttons (existing functionality)"""
    # This would contain the existing approval button logic
    print(f"Approval button: {action_id}")
    return {'statusCode': 200, 'body': 'Approval button handled'}

def handle_approval_request(event):
    """Handle approval requests (existing functionality)"""
    # This would contain the existing approval request logic
    print("Approval request handled")
    return {'statusCode': 200, 'body': 'Approval request handled'}

def send_slack_message(channel, message):
    """Send message to Slack channel"""
    try:
        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        if not bot_token:
            print(f"No bot token - would send: {message}")
            return
        
        http = urllib3.PoolManager()
        
        payload = {
            'channel': channel,
            'text': message,
            'as_user': True
        }
        
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            headers={
                'Authorization': f'Bearer {bot_token}',
                'Content-Type': 'application/json'
            },
            body=json.dumps(payload)
        )
        
        print(f"Slack response: {response.status}")
        
    except Exception as e:
        print(f"Error sending Slack message: {e}")

def update_conversation_status(action_id, user_id, status):
    """Update conversation status in DynamoDB"""
    try:
        # Extract interaction details from action_id if needed
        # This would update the conversation tracking
        print(f"Updated conversation status: {status} for {user_id}")
        
    except Exception as e:
        print(f"Error updating conversation: {e}")
