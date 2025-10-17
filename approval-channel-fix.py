import json
import boto3
import os
import urllib3
from datetime import datetime

def lambda_handler(event, context):
    """IT Approval System with correct channel"""
    
    action = event.get('action')
    
    if action == 'create_approval':
        return create_approval_request(event)
    else:
        return {'statusCode': 200, 'body': 'OK'}

def create_approval_request(event):
    """Create approval request"""
    request_type = event.get('request_type')
    user_email = event.get('user_email')
    group_name = event.get('group_name')
    details = event.get('details')
    action_id = event.get('action_id', f"approval_{int(datetime.now().timestamp())}")
    
    message = f"""🚨 IT Automation Approval Request

Type: {request_type}
Details: {details}
Requested by: {user_email}

Action ID: {action_id}"""
    
    # Try multiple channel approaches
    channels_to_try = [
        'C07NZQZQZQZ',  # Original
        'C07NZQZQZQ0',  # Variation
        '@matthew.denecke',  # Direct message as test
        'general'  # Fallback
    ]
    
    success = False
    for channel in channels_to_try:
        if send_slack_message(channel, message, action_id):
            print(f"✅ Sent to channel: {channel}")
            success = True
            break
        else:
            print(f"❌ Failed to send to channel: {channel}")
    
    if success:
        return {'statusCode': 200, 'body': 'Approval request sent'}
    else:
        return {'statusCode': 500, 'body': 'Failed to send to any channel'}

def send_slack_message(channel, message, action_id=None):
    """Send message to Slack"""
    try:
        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        if not bot_token:
            print(f"No bot token")
            return False
        
        http = urllib3.PoolManager()
        
        payload = {
            'channel': channel,
            'text': message
        }
        
        if action_id:
            payload['attachments'] = [{
                'callback_id': action_id,
                'actions': [
                    {
                        'name': 'approve',
                        'text': 'Approve',
                        'type': 'button',
                        'value': 'approve',
                        'style': 'primary'
                    },
                    {
                        'name': 'deny', 
                        'text': 'Deny',
                        'type': 'button',
                        'value': 'deny',
                        'style': 'danger'
                    }
                ]
            }]
        
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            headers={
                'Authorization': f'Bearer {bot_token}',
                'Content-Type': 'application/json'
            },
            body=json.dumps(payload)
        )
        
        print(f"Slack API response for {channel}: {response.status}")
        if response.status == 200:
            response_data = json.loads(response.data.decode('utf-8'))
            print(f"Slack response data: {response_data}")
            return response_data.get('ok', False)
        
        return False
        
    except Exception as e:
        print(f"Error sending to {channel}: {e}")
        return False
