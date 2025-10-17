import json
import boto3
import re
from datetime import datetime

def lambda_handler(event, context):
    """SOP workflow with proper mapping"""
    
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
    """Handle DL requests with SOP mapping first"""
    user_email = "matthew.denecke@dairy.com"
    
    # SOP mapping - check this FIRST
    sop_mapping = get_sop_mapping(message)
    if sop_mapping:
        # Direct SOP match - send to approval
        lambda_client = boto3.client('lambda')
        lambda_client.invoke(
            FunctionName='it-approval-system',
            Payload=json.dumps({
                'action': 'create_approval',
                'request_type': 'DISTRIBUTION_LIST',
                'user_id': user_id,
                'user_email': user_email,
                'group_name': sop_mapping,
                'details': f"Add Matthew Denecke to {sop_mapping} distribution list (Current Request)",
                'requester': user_email,
                'action_id': f"dl_{int(datetime.now().timestamp())}"
            })
        )
        return {'statusCode': 200, 'body': f'DL request submitted for {sop_mapping}'}
    
    # No SOP match - extract name and send to brie-ad-group-manager for fuzzy search
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

def get_sop_mapping(message):
    """Check SOP mapping first"""
    sop_mappings = {
        'employees': 'All Ever.Ag Employees',
        'all employees': 'All Ever.Ag Employees',
        'usa employees': 'USA Employees',
        'canada employees': 'Canada Employees',
        'brazil employees': 'Brazil Employees'
    }
    
    for key, value in sop_mappings.items():
        if key in message:
            return value
    
    return None

def extract_dl_name(message):
    """Extract DL name for fuzzy search"""
    match = re.search(r'add me to (?:the )?(.+?)(?:\s+dl|\s+distribution)', message)
    if match:
        return match.group(1).strip().title()
    
    match = re.search(r'add me to (.+)', message)
    if match:
        extracted = match.group(1).strip()
        extracted = re.sub(r'\s+(dl|distribution list|distro)$', '', extracted, flags=re.IGNORECASE)
        return extracted.title()
    
    return 'Employees'

def extract_group_name(message):
    """Extract SSO group name"""
    if 'clickup' in message:
        return 'ClickUp'
    elif 'aws' in message:
        return 'SSO AWS Ever.Ag Infra Sandbox Admin'
    elif 'salesforce' in message:
        return 'salesforce sso'
    
    match = re.search(r'add me to (.+)', message)
    return match.group(1).strip() if match else 'Unknown Group'

def handle_user_selection(message, user_id, channel):
    """Handle user selection from fuzzy search"""
    user_email = "matthew.denecke@dairy.com"
    
    # Check if message matches any of the common group names
    group_options = [
        'SP_ALLROGEREMPLOYEES', 'All Ever.Ag Employees', 'USA Employees',
        'Canada Employees', 'Brazil Employees', 'India Employees',
        'Australia Employees', 'New Zealand Employees', 'Ireland Employees', 'UK Employees'
    ]
    
    selected_group = None
    for group in group_options:
        if group.lower() in message.lower() or message.lower() in group.lower():
            selected_group = group
            break
    
    if selected_group:
        # Resubmit to approval with selected group
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
        return True
    
    return False
