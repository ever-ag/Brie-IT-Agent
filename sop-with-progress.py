import json
import boto3
import re
from datetime import datetime

def lambda_handler(event, context):
    """SOP workflow with progress messages"""
    
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
    else:
        message = event.get('message', '').lower()
        user_id = event.get('user_id')
        channel = event.get('channel')
    
    # Send initial progress message
    if 'body' in event:
        send_slack_message(channel, "🔍 Checking your request...")
    
    # Check if this is a user selection response
    if handle_user_selection(message, user_id, channel):
        return {'statusCode': 200, 'body': 'Selection processed'}
    
    # Process new requests
    if any(keyword in message for keyword in ['distribution list', 'dl', 'employees']):
        return handle_dl_request(message, user_id, channel)
    elif any(keyword in message for keyword in ['sso', 'clickup', 'aws', 'salesforce']):
        return handle_sso_request(message, user_id, channel)
    
    return {'statusCode': 200, 'body': 'OK'}

def handle_dl_request(message, user_id, channel):
    """Handle DL requests - show SOP list first"""
    
    # Check if this matches SOP pattern
    if is_sop_request(message):
        # Show SOP list directly
        send_sop_list(channel)
        return {'statusCode': 200, 'body': 'SOP list sent'}
    
    # Not SOP - do fuzzy search with progress
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

def handle_sso_request(message, user_id, channel):
    """Handle SSO requests with progress"""
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
            'action_id': f"sso_{int(datetime.now().timestamp())}"
        })
    )
    
    send_slack_message(channel, "✅ Your SSO request is being processed. IT will review and approve shortly.")
    
    return {'statusCode': 200, 'body': f'SSO request submitted for {group_name}'}

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
    for group in sop_options:
        if group.lower() == message.strip().lower():
            selected_group = group
            break
    
    if selected_group:
        send_slack_message(channel, "🔄 Still working on it...")
        
        # Send to approval system
        lambda_client = boto3.client('lambda')
        lambda_client.invoke(
            FunctionName='it-approval-system',
            Payload=json.dumps({
                'action': 'create_approval',
                'request_type': 'DISTRIBUTION_LIST',
                'user_id': user_id,
                'user_email': user_email,
                'group_name': selected_group,
                'details': f"Add Matthew Denecke to {selected_group} (User Selected)",
                'requester': user_email,
                'action_id': f"dl_selected_{int(datetime.now().timestamp())}"
            })
        )
        
        send_slack_message(channel, "✅ Your distribution list request is being processed. IT will review and approve shortly.")
        return True
    
    return False

def send_slack_message(channel, message):
    """Send message to Slack channel"""
    print(f"Slack message to {channel}: {message}")
