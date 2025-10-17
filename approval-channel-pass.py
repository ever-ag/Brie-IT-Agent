import json
import boto3
import os
import urllib3
import urllib.parse
from datetime import datetime

def lambda_handler(event, context):
    """IT Approval System with channel passing"""
    
    # Handle Slack interactions (button clicks)
    if 'body' in event:
        body = event.get('body', '')
        if 'payload=' in body:
            payload_str = body.split('payload=')[1]
            payload = json.loads(urllib.parse.unquote(payload_str))
            
            user = payload.get('user', {})
            approver_name = user.get('name', 'Unknown')
            
            actions = payload.get('actions', [])
            if actions:
                action = actions[0]
                action_id = action.get('action_id')
                value = action.get('value', '')
                
                if action_id == 'approve_button':
                    action_id_clean = value.replace('approve_', '')
                    return approve_request(action_id_clean, approver_name)
                elif action_id == 'deny_button':
                    action_id_clean = value.replace('deny_', '')
                    return deny_request(action_id_clean, approver_name)
    
    # Handle direct invocations
    action = event.get('action')
    if action == 'create_approval':
        return create_approval_request(event)
    
    return {'statusCode': 200, 'body': 'OK'}

def create_approval_request(event):
    """Create approval request"""
    request_type = event.get('request_type')
    user_email = event.get('user_email')
    group_name = event.get('group_name')
    details = event.get('details')
    action_id = event.get('action_id', f"approval_{int(datetime.now().timestamp())}")
    user_id = event.get('user_id', 'U07NZQZQZQZ')  # Default user ID
    
    message = f"""🚨 IT Automation Approval Request

Type: {request_type}
Details: {details}
Requested by: {user_email}

Action ID: {action_id}"""
    
    # Store request details for later use
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        table.put_item(Item={
            'action_id': action_id,
            'request_type': request_type,
            'user_email': user_email,
            'group_name': group_name,
            'user_id': user_id,
            'status': 'pending',
            'created_at': int(datetime.now().timestamp())
        })
    except Exception as e:
        print(f"Failed to store request: {e}")
    
    success = send_slack_message('C09KB40PL9J', message, action_id)
    
    if success:
        return {'statusCode': 200, 'body': 'Approval request sent'}
    else:
        return {'statusCode': 500, 'body': 'Failed to send to channel'}

def approve_request(action_id, approver_name):
    """Handle approve button click"""
    
    # Send confirmation to approval channel
    send_slack_message('C09KB40PL9J', f"✅ **Request Approved**\nAction ID: {action_id}\nApproved by: {approver_name}")
    
    # Get request details
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        response = table.get_item(Key={'action_id': action_id})
        if 'Item' in response:
            item = response['Item']
            user_email = item.get('user_email', 'matthew.denecke@dairy.com')
            group_name = item.get('group_name', 'SSO AWS Ever.Ag Infra Sandbox Admin')
            user_id = item.get('user_id', 'U07NZQZQZQZ')
        else:
            # Fallback values
            user_email = 'matthew.denecke@dairy.com'
            group_name = 'SSO AWS Ever.Ag Infra Sandbox Admin'
            user_id = 'U07NZQZQZQZ'
    except Exception as e:
        print(f"Failed to get request details: {e}")
        user_email = 'matthew.denecke@dairy.com'
        group_name = 'SSO AWS Ever.Ag Infra Sandbox Admin'
        user_id = 'U07NZQZQZQZ'
    
    # Execute the request with user context
    lambda_client = boto3.client('lambda')
    lambda_client.invoke(
        FunctionName='brie-ad-group-manager',
        Payload=json.dumps({
            'user_email': user_email,
            'group_name': group_name,
            'action': 'add',
            'source': 'it-approval-system',
            'approver': approver_name,
            'action_id': action_id,
            'slackContext': {
                'channel': 'D07NZQZQZQZ',  # Direct message to user
                'user': user_id
            }
        })
    )
    
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({'text': f'✅ {approver_name} approved this request'})
    }

def deny_request(action_id, approver_name):
    """Handle deny button click"""
    
    # Send confirmation to approval channel
    send_slack_message('C09KB40PL9J', f"❌ **Request Denied**\nAction ID: {action_id}\nDenied by: {approver_name}")
    
    # Send denial message directly to user
    send_slack_message('D07NZQZQZQZ', f"❌ Your SSO request has been denied by {approver_name}")
    
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({'text': f'❌ {approver_name} denied this request'})
    }

def send_slack_message(channel, message, action_id=None):
    """Send message to Slack"""
    try:
        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        if not bot_token:
            return False
        
        http = urllib3.PoolManager()
        
        payload = {
            'channel': channel,
            'text': message
        }
        
        if action_id:
            payload['blocks'] = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Approve"
                            },
                            "style": "primary",
                            "value": f"approve_{action_id}",
                            "action_id": "approve_button"
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Deny"
                            },
                            "style": "danger",
                            "value": f"deny_{action_id}",
                            "action_id": "deny_button"
                        }
                    ]
                }
            ]
        
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            headers={
                'Authorization': f'Bearer {bot_token}',
                'Content-Type': 'application/json'
            },
            body=json.dumps(payload)
        )
        
        return response.status == 200
        
    except Exception as e:
        print(f"Error: {e}")
        return False
