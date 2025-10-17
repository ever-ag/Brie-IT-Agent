import json
import boto3
import re
import os
import urllib3
from datetime import datetime

def lambda_handler(event, context):
    """SOP workflow with async routing"""
    
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
    
    # Check if this is a user selection response first
    if handle_user_selection(message, user_id, channel):
        return {'statusCode': 200, 'body': 'Selection processed'}
    
    # Process new requests with SOP first, then route to it-action-processor
    if any(keyword in message for keyword in ['distribution list', 'dl', 'employees']):
        return handle_dl_request(message, user_id, channel)
    elif is_sso_request(message):
        return handle_sso_request(message, user_id, channel)
    else:
        # Route general IT messages to it-action-processor async
        route_to_it_processor_async(event)
        return {'statusCode': 200, 'body': 'Routed to IT processor'}

def route_to_it_processor_async(event):
    """Route to it-action-processor asynchronously"""
    try:
        lambda_client = boto3.client('lambda')
        lambda_client.invoke(
            FunctionName='it-action-processor',
            InvocationType='Event',  # Async invocation
            Payload=json.dumps(event)
        )
        print("✅ Routed to it-action-processor")
        
    except Exception as e:
        print(f"❌ Error routing to it-action-processor: {e}")

def is_sso_request(message):
    """Check if this is specifically an SSO request"""
    sso_patterns = [
        'add me to clickup',
        'add me to aws',
        'add me to salesforce',
        'add me to workday',
        'give me access to clickup',
        'give me access to aws',
        'give me access to salesforce',
        'give me access to workday',
        'need access to clickup',
        'need access to aws',
        'need access to salesforce',
        'need access to workday'
    ]
    
    return any(pattern in message for pattern in sso_patterns)

def handle_sso_request(message, user_id, channel):
    """Handle SSO requests with channel info"""
    if channel:
        send_slack_message(channel, "🔍 Checking your request...")
        send_slack_message(channel, "🔄 Still working on it...")
    
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

def handle_dl_request(message, user_id, channel):
    """Handle DL requests - show SOP list first"""
    
    if channel:
        send_slack_message(channel, "🔍 Checking your request...")
    
    # Check if this matches SOP pattern
    if is_sop_request(message):
        send_sop_list(channel)
        return {'statusCode': 200, 'body': 'SOP list sent'}
    
    # Not SOP - do fuzzy search with progress
    if channel:
        send_slack_message(channel, "🔄 Still working on it...")
    
    group_name = extract_dl_name(message)
    user_email = "matthew.denecke@dairy.com"
    
    lambda_client = boto3.client('lambda')
    lambda_client.invoke(
        FunctionName='brie-ad-group-manager',
        Payload=json.dumps({
            'user_email': user_email,
            'group_name': group_name,
            'action': 'add',
            'source': 'it-helpdesk-bot',
            'slackContext': {'channel': channel, 'user': user_id}
        })
    )
    
    return {'statusCode': 200, 'body': f'Searching for {group_name}'}

def is_sop_request(message):
    """Check if this is a SOP request pattern"""
    sop_patterns = [
        'add me to the employees dl',
        'add me to employees dl',
        'add me to the employees distribution list',
        'add me to employees distribution list'
    ]
    
    normalized_message = message.strip().lower()
    return normalized_message in sop_patterns

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

def extract_dl_name(message):
    """Extract DL name for fuzzy search"""
    match = re.search(r'add me to (?:the )?(.+?)(?:\s+dl|\s+distribution)', message)
    if match:
        return match.group(1).strip().title()
    
    return 'Employees'

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
        
        # Send DIRECTLY to brie-ad-group-manager with the EXACT selected group name
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
