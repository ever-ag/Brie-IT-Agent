import json
import boto3
import re
import os
import urllib3
from datetime import datetime

def lambda_handler(event, context):
    """Original comprehensive IT system with minimal SOP integration"""
    
    if 'body' in event:
        body = json.loads(event['body'])
        if body.get('type') == 'url_verification':
            return {'statusCode': 200, 'body': body['challenge']}
        
        slack_event = body.get('event', {})
        if slack_event.get('type') != 'message' or 'bot_id' in slack_event:
            return {'statusCode': 200, 'body': 'OK'}
        
        message = slack_event.get('text', '').lower()
        user_id = slack_event.get('user')
        channel = slack_event.get('channel')
        ts = slack_event.get('ts')
        
        # DynamoDB deduplication
        if is_duplicate_message(user_id, channel, ts, message):
            return {'statusCode': 200, 'body': 'Duplicate message ignored'}
        
    else:
        message = event.get('message', '').lower()
        user_id = event.get('user_id')
        channel = event.get('channel')
    
    # Check for SOP user selection first
    if handle_user_selection(message, user_id, channel):
        return {'statusCode': 200, 'body': 'Selection processed'}
    
    # Check for very specific SOP patterns only
    if is_exact_sop_dl_request(message):
        return handle_sop_dl_request(message, user_id, channel)
    elif is_exact_sso_request(message):
        return handle_sso_request(message, user_id, channel)
    else:
        # Route everything else to original comprehensive IT system
        return route_to_original_system(event)

def is_exact_sop_dl_request(message):
    """Only exact SOP DL patterns"""
    sop_patterns = [
        'add me to the employees dl',
        'add me to employees dl',
        'add me to the employees distribution list',
        'add me to employees distribution list'
    ]
    return message.strip().lower() in sop_patterns

def is_exact_sso_request(message):
    """Only exact SSO request patterns"""
    exact_patterns = [
        'add me to clickup',
        'add me to aws sso',
        'add me to salesforce',
        'add me to workday',
        'give me access to clickup',
        'give me access to aws sso',
        'give me access to salesforce', 
        'give me access to workday'
    ]
    return message.strip().lower() in exact_patterns

def handle_sop_dl_request(message, user_id, channel):
    """Handle SOP DL request - show predefined list"""
    if channel:
        send_slack_message(channel, "🔍 Checking your request...")
    
    send_sop_list(channel)
    return {'statusCode': 200, 'body': 'SOP list sent'}

def handle_sso_request(message, user_id, channel):
    """Handle SSO requests with approval workflow"""
    if channel:
        send_slack_message(channel, "🔍 Checking your request...")
    
    group_name = extract_group_name(message)
    user_email = "matthew.denecke@dairy.com"
    
    lambda_client = boto3.client('lambda')
    lambda_client.invoke(
        FunctionName='it-approval-system',
        Payload=json.dumps({
            'action': 'create_approval',
            'request_type': 'SSO_GROUP',
            'user_id': user_id,
            'user_email': user_email,
            'group_name': group_name,
            'details': f"Add Matthew Denecke to {group_name} group (Current Request)",
            'requester': user_email,
            'action_id': f"sso_{int(datetime.now().timestamp())}",
            'channel': channel
        })
    )
    
    if channel:
        send_slack_message(channel, "✅ Your SSO request is being processed. IT will review and approve shortly.")
    
    return {'statusCode': 200, 'body': f'SSO request submitted for {group_name}'}

def route_to_original_system(event):
    """Route to original comprehensive IT system"""
    try:
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName='it-action-processor',
            Payload=json.dumps(event)
        )
        
        result = json.loads(response['Payload'].read())
        return result
        
    except Exception as e:
        print(f"Error routing to original system: {e}")
        # Fallback response
        return {'statusCode': 200, 'body': 'Request processed'}

def send_sop_list(channel):
    """Send SOP list to user"""
    sop_options = [
        'SP_ALLROGEREMPLOYEES',
        'All Ever.Ag Employees', 
        'USA Employees',
        'Canada Employees',
        'Brazil Employees',
        'India Employees',
        'Australia Employees',
        'New Zealand Employees',
        'Ireland Employees',
        'UK Employees'
    ]
    
    message = "**Employee Distribution Lists**\n\nPlease select from:\n\n"
    for option in sop_options:
        message += f"• {option}\n"
    message += "\nPlease reply with the exact group name you want."
    
    send_slack_message(channel, message)

def handle_user_selection(message, user_id, channel):
    """Handle user selection from SOP list"""
    user_email = "matthew.denecke@dairy.com"
    
    sop_options = [
        'SP_ALLROGEREMPLOYEES',
        'All Ever.Ag Employees', 
        'USA Employees',
        'Canada Employees',
        'Brazil Employees',
        'India Employees',
        'Australia Employees',
        'New Zealand Employees',
        'Ireland Employees',
        'UK Employees'
    ]
    
    selected_group = None
    message_clean = message.strip()
    
    # Check for exact match (case insensitive)
    for group in sop_options:
        if group.lower() == message_clean.lower():
            selected_group = group
            break
    
    if selected_group:
        if channel:
            send_slack_message(channel, "🔄 Still working on it...")
        
        # Send to brie-ad-group-manager with exact selected group name
        lambda_client = boto3.client('lambda')
        lambda_client.invoke(
            FunctionName='brie-ad-group-manager',
            Payload=json.dumps({
                'user_email': user_email,
                'group_name': selected_group,
                'action': 'add',
                'source': 'it-helpdesk-bot',
                'slackContext': {'channel': channel, 'user': user_id}
            })
        )
        
        return True
    
    return False

def extract_group_name(message):
    """Extract SSO group name"""
    if 'clickup' in message:
        return 'ClickUp'
    elif 'aws' in message:
        return 'SSO AWS Ever.Ag Infra Sandbox Admin'
    elif 'salesforce' in message:
        return 'salesforce sso'
    elif 'workday' in message:
        return 'workday sso'
    
    return 'Unknown Group'

def send_slack_message(channel, message):
    """Send message to Slack channel using bot token"""
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

def is_duplicate_message(user_id, channel, ts, message):
    """Check if message is duplicate using DynamoDB"""
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('it-actions')
        
        message_key = f"dedup_{user_id}_{channel}_{ts}"
        
        table.put_item(
            Item={
                'action_id': message_key,
                'message': message,
                'timestamp': int(datetime.now().timestamp()),
                'ttl': int(datetime.now().timestamp()) + 3600
            },
            ConditionExpression='attribute_not_exists(action_id)'
        )
        
        return False
        
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return True
    except Exception as e:
        print(f"Dedup error: {e}")
        return False
