import json
import boto3
import os
import urllib3
from datetime import datetime

def lambda_handler(event, context):
    """IT Approval System - send to Slack even if DynamoDB fails"""
    
    action = event.get('action')
    
    if action == 'create_approval':
        return create_approval_request(event)
    elif action == 'execute':
        return execute_approval(event)
    else:
        return handle_slack_interaction(event)

def create_approval_request(event):
    """Create approval request - prioritize Slack message"""
    request_type = event.get('request_type')
    user_email = event.get('user_email')
    group_name = event.get('group_name')
    details = event.get('details')
    action_id = event.get('action_id', f"approval_{int(datetime.now().timestamp())}")
    
    # Send to IT approval channel FIRST
    message = f"""🚨 **IT Automation Approval Request**

Type: {request_type}
Details: {details}
Requested by: {user_email}

Action ID: {action_id}"""
    
    # Send to Slack regardless of DynamoDB status
    slack_success = send_slack_message('C07NZQZQZQZ', message, action_id)
    
    # Try to store in DynamoDB (optional)
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        table.put_item(Item={
            'action_id': action_id,
            'request_type': request_type,
            'user_email': user_email,
            'group_name': group_name,
            'details': details,
            'status': 'pending',
            'created_at': int(datetime.now().timestamp())
        })
        print(f"✅ Stored approval request: {action_id}")
        
    except Exception as e:
        print(f"⚠️ DynamoDB storage failed (continuing anyway): {e}")
    
    if slack_success:
        return {'statusCode': 200, 'body': 'Approval request sent to Slack'}
    else:
        return {'statusCode': 500, 'body': 'Failed to send to Slack'}

def handle_slack_interaction(event):
    """Handle Slack button interactions"""
    if 'body' in event:
        body = json.loads(event['body'])
        
        if body.get('type') == 'url_verification':
            return {'statusCode': 200, 'body': body['challenge']}
        
        # Handle button clicks
        if 'payload' in body:
            payload = json.loads(body['payload'])
            action_id = payload.get('callback_id')
            user = payload.get('user', {})
            approver_name = user.get('name', 'Unknown')
            approver_id = user.get('id', 'Unknown')
            
            actions = payload.get('actions', [])
            if actions:
                action_value = actions[0].get('value')
                
                if action_value == 'approve':
                    return approve_request(action_id, approver_name, approver_id)
                elif action_value == 'deny':
                    return deny_request(action_id, approver_name, approver_id)
    
    return {'statusCode': 200, 'body': 'OK'}

def approve_request(action_id, approver_name, approver_id):
    """Approve request"""
    
    # Try to get request details from DynamoDB
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        response = table.get_item(Key={'action_id': action_id})
        if 'Item' in response:
            item = response['Item']
            
            # Update with approver info
            table.update_item(
                Key={'action_id': action_id},
                UpdateExpression='SET #status = :status, approver_name = :name, approver_id = :id, approved_at = :timestamp',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'approved',
                    ':name': approver_name,
                    ':id': approver_id,
                    ':timestamp': int(datetime.now().timestamp())
                }
            )
            
            # Execute the request
            lambda_client = boto3.client('lambda')
            lambda_client.invoke(
                FunctionName='brie-ad-group-manager',
                Payload=json.dumps({
                    'user_email': item.get('user_email', item.get('requester')),
                    'group_name': item.get('group_name'),
                    'action': 'add',
                    'source': 'it-approval-system',
                    'approver': approver_name,
                    'action_id': action_id
                })
            )
            
            # Send approval confirmation
            send_slack_message('C07NZQZQZQZ', f"✅ **Request Approved**\nAction ID: {action_id}\nApproved by: {approver_name}")
            
        else:
            # No DynamoDB record - send generic approval
            send_slack_message('C07NZQZQZQZ', f"✅ **Request Approved**\nAction ID: {action_id}\nApproved by: {approver_name}")
        
    except Exception as e:
        print(f"Error in approval process: {e}")
        # Send generic approval message
        send_slack_message('C07NZQZQZQZ', f"✅ **Request Approved**\nAction ID: {action_id}\nApproved by: {approver_name}")
    
    return {'statusCode': 200, 'body': f'✅ approved this request'}

def deny_request(action_id, approver_name, approver_id):
    """Deny request"""
    
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        table.update_item(
            Key={'action_id': action_id},
            UpdateExpression='SET #status = :status, approver_name = :name, approver_id = :id, denied_at = :timestamp',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'denied',
                ':name': approver_name,
                ':id': approver_id,
                ':timestamp': int(datetime.now().timestamp())
            }
        )
        
    except Exception as e:
        print(f"Error updating denial: {e}")
    
    send_slack_message('C07NZQZQZQZ', f"❌ **Request Denied**\nAction ID: {action_id}\nDenied by: {approver_name}")
    
    return {'statusCode': 200, 'body': f'❌ denied this request'}

def send_slack_message(channel, message, action_id=None):
    """Send message to Slack with optional approval buttons"""
    try:
        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        if not bot_token:
            print(f"No bot token - would send: {message}")
            return False
        
        http = urllib3.PoolManager()
        
        payload = {
            'channel': channel,
            'text': message,
            'as_user': True
        }
        
        # Add approval buttons if action_id provided
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
        
        print(f"Slack response: {response.status}")
        return response.status == 200
        
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return False

def execute_approval(event):
    """Execute approved request"""
    action_id = event.get('action_id')
    
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        table.update_item(
            Key={'action_id': action_id},
            UpdateExpression='SET #status = :status, executed_at = :timestamp',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'completed',
                ':timestamp': int(datetime.now().timestamp())
            }
        )
        
    except Exception as e:
        print(f"Error recording execution: {e}")
    
    return {'statusCode': 200, 'body': 'Execution recorded'}
