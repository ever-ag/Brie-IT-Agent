import re

# Read the original file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence.py', 'r') as f:
    content = f.read()

# SOP functions to add
sop_functions = '''
import urllib3

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
        'add me to clickup sso group',
        'add me to clickup',
        'give me access to clickup'
    ]
    return message.strip().lower() in exact_patterns

def handle_sop_dl_request(message, user_id, channel):
    """Handle SOP DL request - show predefined list"""
    if channel:
        send_sop_slack_message(channel, "🔍 Checking your request...")
    
    send_sop_list(channel)
    return {'statusCode': 200, 'body': 'SOP list sent'}

def handle_sop_sso_request(message, user_id, channel):
    """Handle SSO requests with SOP approval workflow"""
    if channel:
        send_sop_slack_message(channel, "🔍 Checking your request...")
    
    group_name = 'ClickUp'
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
            'details': f"Add Matthew Denecke to {group_name} group (SOP Request)",
            'requester': user_email,
            'action_id': f"sso_{int(datetime.now().timestamp())}",
            'channel': channel
        })
    )
    
    if channel:
        send_sop_slack_message(channel, "✅ Your SSO request is being processed. IT will review and approve shortly.")
    
    return {'statusCode': 200, 'body': f'SSO request submitted for {group_name}'}

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
    
    message = "**Employee Distribution Lists**\\n\\nPlease select from:\\n\\n"
    for option in sop_options:
        message += f"• {option}\\n"
    message += "\\nPlease reply with the exact group name you want."
    
    send_sop_slack_message(channel, message)

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
            send_sop_slack_message(channel, "🔄 Still working on it...")
        
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

def send_sop_slack_message(channel, message):
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

'''

# Add SOP functions after imports
import_end = content.find('# Initialize AWS services')
new_content = content[:import_end] + sop_functions + '\n' + content[import_end:]

# Find lambda_handler function and add SOP checks
handler_start = new_content.find('def lambda_handler(event, context):')
handler_body_start = new_content.find('print(f"Received event: {json.dumps(event)}")', handler_start)
handler_try_start = new_content.find('try:', handler_body_start)

sop_checks = '''
        # SOP workflow checks first
        if 'body' in event:
            body = json.loads(event['body'])
            if body.get('type') == 'url_verification':
                return {'statusCode': 200, 'body': body['challenge']}
            
            slack_event = body.get('event', {})
            if slack_event.get('type') == 'message' and 'bot_id' not in slack_event:
                message = slack_event.get('text', '').lower()
                user_id = slack_event.get('user')
                channel = slack_event.get('channel')
                
                # Check SOP patterns first
                if handle_user_selection(message, user_id, channel):
                    return {'statusCode': 200, 'body': 'Selection processed'}
                
                if is_exact_sop_dl_request(message):
                    return handle_sop_dl_request(message, user_id, channel)
                elif is_exact_sso_request(message):
                    return handle_sop_sso_request(message, user_id, channel)
        
        # Continue with original comprehensive system
'''

# Insert SOP checks after the try statement
try_line_end = new_content.find('\n', handler_try_start)
final_content = new_content[:try_line_end] + '\n' + sop_checks + new_content[try_line_end:]

# Write the modified file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_with_sop_final.py', 'w') as f:
    f.write(final_content)

print("SOP integration added successfully!")
