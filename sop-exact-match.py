import json
import boto3
import re
from datetime import datetime

def lambda_handler(event, context):
    """SOP workflow with exact 1-to-1 mapping"""
    
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
    """Handle DL requests with exact SOP mapping"""
    user_email = "matthew.denecke@dairy.com"
    
    # Exact SOP mapping - must match exactly
    exact_group = get_exact_sop_mapping(message)
    if exact_group:
        # Send directly to brie-ad-group-manager with exact group name
        lambda_client = boto3.client('lambda')
        lambda_client.invoke(
            FunctionName='brie-ad-group-manager',
            Payload=json.dumps({
                'user_email': user_email,
                'group_name': exact_group,
                'action': 'add',
                'source': 'it-helpdesk-bot',
                'slackContext': {'channel': channel, 'user': user_id}
            })
        )
        return {'statusCode': 200, 'body': f'Processing {exact_group}'}
    
    # No exact match - do fuzzy search
    group_name = extract_dl_name(message)
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

def get_exact_sop_mapping(message):
    """Exact 1-to-1 SOP mapping"""
    # Exact phrase matches only
    sop_mappings = {
        'add me to the employees dl': 'All Ever.Ag Employees',
        'add me to employees dl': 'All Ever.Ag Employees',
        'add me to the employees distribution list': 'All Ever.Ag Employees',
        'add me to employees distribution list': 'All Ever.Ag Employees'
    }
    
    # Check for exact match
    normalized_message = message.strip().lower()
    return sop_mappings.get(normalized_message)

def handle_sso_request(message, user_id, channel):
    """Handle SSO requests"""
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
    """Handle user selection from fuzzy search"""
    user_email = "matthew.denecke@dairy.com"
    
    group_options = [
        'SP_ALLROGEREMPLOYEES', 'All Ever.Ag Employees', 'USA Employees',
        'Canada Employees', 'Brazil Employees', 'India Employees',
        'Australia Employees', 'New Zealand Employees', 'Ireland Employees', 'UK Employees'
    ]
    
    selected_group = None
    for group in group_options:
        if group.lower() == message.strip().lower():
            selected_group = group
            break
    
    if selected_group:
        # Send directly to brie-ad-group-manager with selected group
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
