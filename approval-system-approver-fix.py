import json
import boto3
import os
import urllib3
from datetime import datetime

def lambda_handler(event, context):
    """IT Approval System with proper approver tracking"""
    
    action = event.get('action')
    
    if action == 'create_approval':
        return create_approval_request(event)
    elif action == 'execute':
        return execute_approval(event)
    else:
        return handle_slack_interaction(event)

def create_approval_request(event):
    """Create approval request"""
    request_type = event.get('request_type')
    user_email = event.get('user_email')
    group_name = event.get('group_name')
    details = event.get('details')
    action_id = event.get('action_id')
    
    # Send to IT approval channel
    message = f"""🚨 **IT Automation Approval Request**

Type: {request_type}
Details: {details}
Requested by: {user_email}

Action ID: {action_id}"""
    
    send_slack_message('C07NZQZQZQZ', message, action_id)
    
    return {'statusCode': 200, 'body': 'Approval request sent'}

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
    """Approve request with proper approver tracking"""
    
    # Get request details from DynamoDB
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('it-actions')
    
    try:
        response = table.get_item(Key={'action_id': action_id})
        if 'Item' not in response:
            return {'statusCode': 404, 'body': 'Request not found'}
        
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
        send_slack_message('C07NZQZQZQZ', f"✅ **Request Completed**\nUser: {item.get('user_email')}\nGroup: {item.get('group_name')}\nAction: Approved\nApproved by: {approver_name}")
        
        return {'statusCode': 200, 'body': f'✅ approved this request'}
        
    except Exception as e:
        print(f"Error approving request: {e}")
        return {'statusCode': 500, 'body': 'Error processing approval'}

def deny_request(action_id, approver_name, approver_id):
    """Deny request with proper approver tracking"""
    
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('it-actions')
    
    try:
        # Update with denial info
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
        
        send_slack_message('C07NZQZQZQZ', f"❌ **Request Denied**\nAction ID: {action_id}\nDenied by: {approver_name}")
        
        return {'statusCode': 200, 'body': f'❌ denied this request'}
        
    except Exception as e:
        print(f"Error denying request: {e}")
        return {'statusCode': 500, 'body': 'Error processing denial'}

def send_slack_message(channel, message, action_id=None):
    """Send message to Slack with optional approval buttons"""
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
        
    except Exception as e:
        print(f"Error sending Slack message: {e}")

def execute_approval(event):
    """Execute approved request"""
    action_id = event.get('action_id')
    
    # This is called by brie-ad-group-manager after execution
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
    
    return {'statusCode': 200, 'body': 'Execution recorded'}
