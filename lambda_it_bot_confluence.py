import json
import boto3
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal
import random
import urllib.request
import urllib.parse
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email import encoders
import uuid

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses')
bedrock = boto3.client('bedrock-runtime')
sfn_client = boto3.client('stepfunctions')
interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

def to_float(value):
    """Convert DynamoDB Decimal to float safely"""
    if isinstance(value, Decimal):
        return float(value)
    return value

# Conversation tracking
CONVERSATION_TIMEOUT_MINUTES = 30
user_conversations = {}  # {user_id: interaction_id}

def get_or_create_conversation(user_id, user_name, message_text):
    """Get existing conversation or create new one with resumption logic"""
    try:
        # Look for active conversations (not closed)
        response = interactions_table.scan(
            FilterExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id}
        )
        
        items = response.get('Items', [])
        if items:
            items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            
            # Check most recent conversation
            recent = items[0]
            last_msg_time = recent.get('last_message_timestamp', recent.get('timestamp', 0))
            last_msg_time = to_float(last_msg_time)
            time_since_last = datetime.utcnow().timestamp() - last_msg_time
            
            # If conversation is active (< 15 min since last message) and not closed
            if time_since_last < (15 * 60) and recent.get('outcome') not in ['Ticket Created', 'Self-Service Solution', 'Resolved by Brie', 'Timed Out - No Response', 'Escalated to IT']:
                return recent['interaction_id'], recent['timestamp'], False
            
            # If conversation closed, always create new one
            # TODO: Add resumption prompt asking if related to previous conversation
        
        # Create new conversation
        interaction_id = str(uuid.uuid4())
        timestamp = int(datetime.utcnow().timestamp())
        interaction_type = categorize_interaction(message_text)
        
        # Redact sensitive data before storing
        redacted_message = redact_sensitive_data(message_text)
        
        item = {
            'interaction_id': interaction_id,
            'timestamp': timestamp,
            'user_id': user_id,
            'user_name': user_name,
            'interaction_type': interaction_type,
            'description': redacted_message[:200],
            'outcome': 'In Progress',
            'date': datetime.utcnow().isoformat(),
            'last_message_timestamp': timestamp,
            'conversation_history': json.dumps([{
                'timestamp': timestamp, 
                'timestamp_ms': timestamp * 1000,
                'message': redacted_message, 
                'from': 'user'
            }]),
            'metadata': '{}'
        }
        
        interactions_table.put_item(Item=item)
        return interaction_id, timestamp, True
    except Exception as e:
        print(f"Error in conversation tracking: {e}")
        return None, 0, True

def redact_sensitive_data(text):
    """Redact sensitive information from conversation history"""
    import re
    
    # Password patterns
    text = re.sub(r'(password|passwd|pwd|pass)\s*(is|:)?\s*\S+', r'\1 *********', text, flags=re.IGNORECASE)
    
    # SSN patterns (XXX-XX-XXXX or XXXXXXXXX)
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '***-**-****', text)
    text = re.sub(r'\b\d{9}\b', '*********', text)
    
    # Credit card patterns (groups of 4 digits)
    text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '****-****-****-****', text)
    
    # API keys/tokens (long alphanumeric strings 32+ chars)
    text = re.sub(r'\b[A-Za-z0-9_-]{32,}\b', '************************', text)
    
    # MFA/2FA codes (6 digit codes)
    text = re.sub(r'\b(code|mfa|2fa|otp)\s*(is|:)?\s*\d{6}\b', r'\1 ******', text, flags=re.IGNORECASE)
    
    return text

def update_conversation(interaction_id, timestamp, message_text, from_bot=False, outcome=None, awaiting_approval=None, update_last_message=True):
    """Update existing conversation"""
    try:
        response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
        if 'Item' not in response:
            return False
        
        item = response['Item']
        conv_hist = item.get('conversation_history', '[]')
        history = json.loads(conv_hist) if isinstance(conv_hist, str) else conv_hist
        if not isinstance(history, list):
            history = []
        
        # Redact sensitive data before storing
        redacted_message = redact_sensitive_data(message_text[:500])
        
        # Store timestamp in both ISO format and Unix epoch for frontend compatibility
        now = datetime.utcnow()
        history.append({
            'timestamp': now.isoformat(),
            'timestamp_ms': int(now.timestamp() * 1000),  # Unix epoch in milliseconds for JavaScript
            'message': redacted_message,
            'from': 'bot' if from_bot else 'user'
        })
        
        # Only update last_message_timestamp if requested (skip for engagement prompts)
        if update_last_message:
            update_expr = 'SET conversation_history = :hist, last_updated = :updated, last_message_timestamp = :last_msg'
            expr_values = {
                ':hist': json.dumps(history), 
                ':updated': now.isoformat(),
                ':last_msg': int(now.timestamp())
            }
        else:
            update_expr = 'SET conversation_history = :hist, last_updated = :updated'
            expr_values = {
                ':hist': json.dumps(history), 
                ':updated': now.isoformat()
            }
        
        if outcome:
            update_expr += ', outcome = :outcome'
            expr_values[':outcome'] = outcome
        
        if awaiting_approval is not None:
            update_expr += ', awaiting_approval = :awaiting'
            expr_values[':awaiting'] = awaiting_approval
        
        interactions_table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values
        )
        return True
    except Exception as e:
        print(f"Error updating conversation: {e}")
        return False

def detect_resolution(message_text):
    """Detect if user indicates issue is resolved"""
    text = message_text.lower().strip()
    resolved_phrases = ['thank', 'thanks', 'that worked', 'that fixed', 'that helped', 'resolved', 'solved', 'fixed', 'working now', 'all set', 'perfect', 'great', 'awesome', 'got it', 'that did it']
    return any(phrase in text for phrase in resolved_phrases)

def detect_no_further_help(message_text):
    """Detect if user indicates they don't need further help"""
    text = message_text.lower().strip()
    no_help_phrases = ['nothing else', 'no thanks', 'nope', 'no', "i'm good", "im good", 'all good', "that's all", "thats all", "that's it", "thats it", 'nothing', 'nah']
    return text in no_help_phrases or (len(text.split()) <= 3 and any(phrase in text for phrase in no_help_phrases))

def send_resolution_prompt(channel, user_id, interaction_id, timestamp):
    """Send follow-up message asking if issue was resolved"""
    try:
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        message = {
            "channel": channel,
            "text": "Did that help resolve your issue?",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "💬 *Did that help resolve your issue?*"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "👍 Yes, that worked!",
                                "emoji": True
                            },
                            "style": "primary",
                            "action_id": f"resolved_{interaction_id}_{timestamp}_{user_id}"
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "👎 Still need help",
                                "emoji": True
                            },
                            "action_id": f"needhelp_{interaction_id}_{timestamp}_{user_id}"
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "🎫 Create ticket",
                                "emoji": True
                            },
                            "action_id": f"ticket_{interaction_id}_{timestamp}_{user_id}"
                        }
                    ]
                }
            ]
        }
        
        req = urllib.request.Request(
            'https://slack.com/api/chat.postMessage',
            data=json.dumps(message).encode('utf-8'),
            headers=headers
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                print(f"✅ Sent resolution prompt to {channel}")
                
                # Schedule auto-resolve after 15 minutes if no response
                schedule_auto_resolve(interaction_id, timestamp, user_id)
            else:
                print(f"❌ Failed to send resolution prompt: {result.get('error')}")
                
    except Exception as e:
        print(f"Error sending resolution prompt: {e}")

def schedule_auto_resolve(interaction_id, timestamp, user_id):
    """Schedule engagement prompts and auto-resolve using EventBridge Scheduler"""
    try:
        scheduler = boto3.client('scheduler')
        lambda_arn = f"arn:aws:lambda:us-east-1:843046951786:function:it-helpdesk-bot"
        role_arn = "arn:aws:iam::843046951786:role/EventBridgeSchedulerRole"
        
        current_time = datetime.utcnow()
        
        # Schedule first engagement prompt at 5 minutes
        schedule_time_1 = current_time + timedelta(minutes=5)
        scheduler.create_schedule(
            Name=f"engagement-1-{interaction_id}-{timestamp}",
            ScheduleExpression=f"at({schedule_time_1.strftime('%Y-%m-%dT%H:%M:%S')})",
            Target={
                'Arn': lambda_arn,
                'RoleArn': role_arn,
                'Input': json.dumps({
                    'engagement_prompt': True,
                    'interaction_id': interaction_id,
                    'timestamp': timestamp,
                    'user_id': user_id,
                    'prompt_number': 1
                })
            },
            FlexibleTimeWindow={'Mode': 'OFF'}
        )
        
        # Schedule second engagement prompt at 10 minutes
        schedule_time_2 = current_time + timedelta(minutes=10)
        scheduler.create_schedule(
            Name=f"engagement-2-{interaction_id}-{timestamp}",
            ScheduleExpression=f"at({schedule_time_2.strftime('%Y-%m-%dT%H:%M:%S')})",
            Target={
                'Arn': lambda_arn,
                'RoleArn': role_arn,
                'Input': json.dumps({
                    'engagement_prompt': True,
                    'interaction_id': interaction_id,
                    'timestamp': timestamp,
                    'user_id': user_id,
                    'prompt_number': 2
                })
            },
            FlexibleTimeWindow={'Mode': 'OFF'}
        )
        
        # Schedule auto-resolve at 15 minutes
        schedule_time_3 = current_time + timedelta(minutes=15)
        scheduler.create_schedule(
            Name=f"auto-resolve-{interaction_id}-{timestamp}",
            ScheduleExpression=f"at({schedule_time_3.strftime('%Y-%m-%dT%H:%M:%S')})",
            Target={
                'Arn': lambda_arn,
                'RoleArn': role_arn,
                'Input': json.dumps({
                    'auto_resolve': True,
                    'interaction_id': interaction_id,
                    'timestamp': timestamp,
                    'user_id': user_id
                })
            },
            FlexibleTimeWindow={'Mode': 'OFF'}
        )
        
        print(f"✅ Scheduled engagement prompts and auto-resolve for {interaction_id}")
    except Exception as e:
        print(f"Error scheduling: {e}")

def handle_resolution_button(action_id, user_id, channel):
    """Handle resolution button clicks"""
    try:
        parts = action_id.split('_')
        action_type = parts[0]
        interaction_id = parts[1]
        timestamp = int(parts[2])
        
        if action_type == 'resolved':
            # Mark as resolved
            update_conversation(interaction_id, timestamp, "User confirmed issue resolved", from_bot=False, outcome='Self-Service Solution')
            send_slack_message(channel, "✅ Great! Glad I could help! Feel free to reach out anytime.")
            
        elif action_type == 'needhelp':
            # Keep conversation open
            send_slack_message(channel, "👍 No problem! What else can I help you with?")
            
        elif action_type == 'ticket':
            # Create ticket with conversation history
            real_name, user_email = get_user_info_from_slack(user_id)
            
            if save_ticket_to_dynamodb(user_id, real_name, user_email, interaction_id, timestamp):
                update_conversation(interaction_id, timestamp, "User created ticket", from_bot=False, outcome='Ticket Created')
                send_slack_message(channel, f"✅ Ticket created with full conversation history. IT will follow up via email: {user_email}")
            else:
                send_slack_message(channel, "❌ Error creating ticket. Please try again.")
                
    except Exception as e:
        print(f"Error handling resolution button: {e}")

def categorize_interaction(message_text):
    """Auto-categorize interaction type"""
    text = message_text.lower()
    if any(kw in text for kw in ['distribution list', ' dl', 'shared mailbox', 'sso', 'access to']):
        return "Access Management"
    elif any(kw in text for kw in ['excel', 'word', 'outlook', 'powerpoint', 'teams', 'slack']):
        return "Application Support"
    elif any(kw in text for kw in ['printer', 'monitor', 'keyboard', 'mouse', 'laptop', 'hardware']):
        return "Hardware Support"
    elif any(kw in text for kw in ['wifi', 'vpn', 'network', 'internet', 'connection', 'slow', 'workspace']):
        return "Network & Connectivity"
    elif any(kw in text for kw in ['password', 'login', 'account', 'authentication', 'mfa']):
        return "Account & Authentication"
    else:
        return "General Support"

def get_conversation_summary(interaction_id, timestamp):
    """Get full conversation history for ticket"""
    try:
        response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
        if 'Item' not in response:
            return None
        
        item = response['Item']
        history = json.loads(item.get('conversation_history', '[]'))
        summary = f"Issue: {item.get('description', 'N/A')}\n\nConversation:\n"
        for msg in history:
            from_label = "User" if msg['from'] == 'user' else "Brie"
            summary += f"\n[{msg['timestamp']}] {from_label}: {msg['message']}\n"
        return summary
    except Exception as e:
        print(f"Error getting conversation summary: {e}")
        return None

def log_bot_interaction(user_name, message_text, action_taken, ticket_created=False, metadata=None):
    """Legacy function - kept for compatibility"""
    pass

SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', 'xoxb-your-token-here')

# Confluence credentials
CONFLUENCE_EMAIL = "mdenecke@dairy.com"
CONFLUENCE_API_TOKEN = os.environ.get('CONFLUENCE_API_TOKEN', 'ATLASSIAN_API_TOKEN')
CONFLUENCE_BASE_URL = "https://everag.atlassian.net/wiki"

# Simple in-memory conversation tracking with full history
user_conversations = {}
user_interaction_ids = {}  # {user_id: {'interaction_id': ..., 'timestamp': ...}}

# Distribution list approval tracking
pending_approvals = {}
pending_executions = {}  # NEW: Track Step Functions executions
IT_APPROVAL_CHANNEL = "C09KB40PL9J"  # IT channel ID
STEP_FUNCTIONS_ARN = "arn:aws:states:us-east-1:843046951786:stateMachine:brie-ticket-processor"

def check_membership(user_email, group_name):
    """Check if user is already a member of the group"""
    try:
        lambda_client = boto3.client('lambda')
        
        payload = {
            'action': 'check_membership',
            'user_email': user_email,
            'group_name': group_name
        }
        
        response = lambda_client.invoke(
            FunctionName='brie-ad-group-validator',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"Membership check result: {result}")
        
        if result.get('statusCode') == 200:
            body = json.loads(result.get('body', '{}'))
            return body.get('membership_status')
        
        return "ERROR"
        
    except Exception as e:
        print(f"Error checking membership: {e}")
        return "ERROR"

def query_group_type(group_name):
    """Query AD to determine if group_name is an SSO group or Distribution List"""
    try:
        # Invoke brie-ad-group-validator to check group type
        lambda_client = boto3.client('lambda')
        
        payload = {
            'action': 'check_group_type',
            'group_name': group_name
        }
        
        response = lambda_client.invoke(
            FunctionName='brie-ad-group-validator',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"Group type query result: {result}")
        
        if result.get('statusCode') == 200:
            body = json.loads(result.get('body', '{}'))
            return body.get('matches')  # Returns list of matches or None
        
        return None
        
    except Exception as e:
        print(f"Error querying group type: {e}")
        return None

def detect_automation_request(message):
    """Detect if message is a DL, Shared Mailbox, or SSO request"""
    message_lower = message.lower()
    
    # SSO Group keywords (explicit)
    if any(kw in message_lower for kw in ['sso', 'active directory', 'ad group']):
        if any(action in message_lower for action in ['add', 'remove', 'grant', 'revoke', 'access']):
            return 'SSO_GROUP'
    
    # Shared Mailbox keywords (check before DL since "shared mailbox" is more specific)
    if any(kw in message_lower for kw in ['shared mailbox', 'mailbox access']):
        return 'SHARED_MAILBOX'
    
    # Check for generic "add me to X group" pattern
    if any(action in message_lower for action in ['add', 'remove', 'grant', 'revoke', 'access']):
        if 'group' in message_lower or 'to' in message_lower:
            # Extract potential group name
            import re
            patterns = [
                r'(?:add|remove|grant|revoke).*?(?:to|from)\s+(?:the\s+)?([a-z0-9\s-]+?)\s+(?:group|sso|dl)',
                r'(?:add|remove|grant|revoke).*?(?:to|from)\s+(?:the\s+)?([a-z0-9\s-]+?)$',
                r'(?:access|permission).*?(?:to|for)\s+(?:the\s+)?([a-z0-9\s-]+?)\s+(?:group|sso|dl)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, message_lower)
                if match:
                    potential_group = match.group(1).strip()
                    print(f"Extracted potential group name: {potential_group}")
                    
                    # Query AD to get matches
                    matches = query_group_type(potential_group)
                    if matches:
                        print(f"Found {len(matches)} matching groups")
                        
                        # Filter by explicit type if user specified "dl" or "sso"
                        if 'dl' in message_lower or 'distribution list' in message_lower:
                            dl_matches = [m for m in matches if m['type'] == 'DISTRIBUTION_LIST']
                            if dl_matches:
                                return 'DISTRIBUTION_LIST'
                            else:
                                # User asked for DL but only SSO groups found
                                print(f"User requested DL but only found SSO groups")
                                return None
                        elif 'sso' in message_lower or 'ad group' in message_lower:
                            sso_matches = [m for m in matches if m['type'] == 'SSO_GROUP']
                            if sso_matches:
                                return 'SSO_GROUP'
                            else:
                                print(f"User requested SSO but only found DLs")
                                return None
                        else:
                            # No explicit type - return first match type
                            return matches[0]['type']
                    else:
                        print(f"No groups found matching: {potential_group}")
    
    # Distribution List - DISABLED: Use simple detect_distribution_list_request() instead
    # The it-action-processor Lambda regex doesn't work well with Slack messages
    # dl_keywords = [
    #     "distribution list",
    #     "dl",
    #     "distlist",
    #     "mailing list",
    #     "add me to",
    #     "add to",
    #     "access to",
    #     "join",
    #     "member of",
    #     "need access to",
    #     "give access to"
    # ]
    # if any(kw in message_lower for kw in dl_keywords):
    #     return 'DISTRIBUTION_LIST'
    
    return None

def check_pending_group_selection(user_email):
    """Check if user has a pending group selection"""
    try:
        table = dynamodb.Table('it-actions')
        response = table.scan(
            FilterExpression='requester = :email AND pending_selection = :flag',
            ExpressionAttributeValues={
                ':email': user_email,
                ':flag': True
            }
        )
        
        items = response.get('Items', [])
        if items:
            # Get most recent item
            items.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            item = items[0]
            
            # Check if it's expired (older than 5 minutes)
            from datetime import datetime, timedelta
            created_at = item.get('created_at', '')
            if created_at:
                try:
                    created_time = datetime.fromisoformat(created_at)
                    if datetime.utcnow() - created_time > timedelta(minutes=5):
                        # Delete expired selection
                        table.delete_item(Key={'action_id': item['action_id']})
                        return None
                except:
                    pass
            
            return item
        
        return None
    except Exception as e:
        print(f"Error checking pending selection: {e}")
        return None

def detect_distribution_list_request(message):
    """Detect if user is requesting to be added to a distribution list"""
    keywords = [
        'add me to', 'distribution list', 'distro list', 'dl', 'mailing list',
        'email group', 'add to group', 'join group', 'subscribe to'
    ]
    
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)

def extract_distribution_list_name(message):
    """Extract the distribution list name from the message"""
    import re
    
    # Look for patterns like "add me to [list name]"
    patterns = [
        r'add me to (.+)',
        r'distribution list (.+)',
        r'distro list (.+)',
        r'mailing list (.+)',
        r'email group (.+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            return match.group(1).strip()
    
    return "unknown list"

def send_slack_message(message_data):
    """Send message to Slack"""
    headers = {
        'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    data = json.dumps(message_data).encode('utf-8')
    req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return None

def extract_distribution_list_name(message):
    """Extract the distribution list name from the message"""
    import re
    
    # Strip Slack formatting: <mailto:email@domain.com|email@domain.com> -> email@domain.com
    message = re.sub(r'<mailto:([^|>]+)\|[^>]+>', r'\1', message)
    message = re.sub(r'<([^|>]+)>', r'\1', message)  # Strip other link formats
    
    # Look for patterns like "add me to [list name]"
    patterns = [
        r'(?:update|modify|change|help.*?with|help.*?updating)\s+(?:the\s+)?["\']?([^"\']+?)["\']?\s+(?:distribution list|dl)',
        r'distribution list[:\s]+["\']?([^"\'\.]+?)["\']?(?:\.|$)',
        r'add me to (?:the )?(.+?)\s+(?:dl|distribution list|distro list)',
        r'add me to (?:the )?(.+?)$',
        r'distro list (.+?)$',
        r'mailing list (.+?)$',
        r'email group (.+?)$',
        r'access to (?:the )?(.+?)\s+(?:dl|distribution list|distro list)',
        r'access to (?:the )?(.+?)$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            extracted = match.group(1).strip()
            # Clean up common noise words
            extracted = re.sub(r'\s+(distribution list|dl|distro list|mailing list)$', '', extracted)
            if extracted and len(extracted) > 2:
                return extracted
    
    return None  # Return None instead of default

def is_bulk_distribution_list_update(message):
    """Detect if user wants to add/remove multiple people from a distribution list"""
    message_lower = message.lower()
    
    # Check for distribution list mention
    has_dl_mention = any(kw in message_lower for kw in ['distribution list', 'all employees', 'dl'])
    
    # Check for bulk operations (multiple bullet points or multiple add/remove)
    has_multiple_items = message.count('•') > 1 or message.count('\n') > 2
    
    # Check for add/remove keywords
    has_bulk_keywords = ('add' in message_lower and 'remove' in message_lower) or \
                       message_lower.count('add') > 1 or \
                       message_lower.count('remove') > 1
    
    return has_dl_mention and (has_multiple_items or has_bulk_keywords)

def send_approval_request(user_id, user_name, user_email, distribution_list, original_message, conv_data=None):
    """Send approval request to IT channel"""
    approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
    
    # Store in DynamoDB for persistence
    table = dynamodb.Table('it-actions')
    table.put_item(Item={
        'action_id': approval_id,
        'action_type': 'dl_approval',
        'status': 'pending',
        'requester': user_email,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'details': {
            'user_id': user_id,
            'user_name': user_name,
            'user_email': user_email,
            'distribution_list': distribution_list,
            'original_message': original_message,
            'interaction_id': conv_data.get('interaction_id') if conv_data else None,
            'interaction_timestamp': conv_data.get('timestamp') if conv_data else None
        }
    })
    
    # Create approval message with buttons
    approval_message = {
        "channel": IT_APPROVAL_CHANNEL,
        "channel": IT_APPROVAL_CHANNEL,
        "text": f"Distribution List Access Request",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Distribution List Access Request*\n\n*User:* {user_name}\n*Email:* {user_email}\n*Requested List:* `{distribution_list}`\n*Original Message:* {original_message}"
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
                        "action_id": f"approve_{approval_id}"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Deny"
                        },
                        "style": "danger",
                        "action_id": f"deny_{approval_id}"
                    }
                ]
            }
        ]
    }
    
    # Send to Slack
    send_slack_message_to_channel(approval_message)
    
    return approval_id

def send_slack_message_to_channel(message_data):
    """Send message to Slack channel"""
    headers = {
        'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    data = json.dumps(message_data).encode('utf-8')
    req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            if not result.get('ok'):
                print(f"❌ Slack API error: {result.get('error')}")
            else:
                print(f"✅ Approval message sent to channel")
            return result
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return None

def handle_approval_response(action_id, user_id):
    """Handle approval/denial response from IT team"""
    table = dynamodb.Table('it-actions')
    
    if action_id.startswith('approve_'):
        approval_id = action_id.replace('approve_', '')
        
        # Get from DynamoDB
        response = table.get_item(Key={'action_id': approval_id})
        if 'Item' in response:
            approval_data = response['Item']['details']
            
            # Notify user of approval
            success_message = f"✅ Your request to join `{approval_data['distribution_list']}` has been approved! Please contact IT to complete the process."
            send_slack_message_to_channel({
                "channel": approval_data['user_id'],
                "text": success_message
            })
            
            # Notify IT channel
            send_slack_message_to_channel({
                "channel": IT_APPROVAL_CHANNEL,
                "text": f"✅ Approved: {approval_data['user_name']} → `{approval_data['distribution_list']}`"
            })
            
            # Update conversation outcome if tracked
            interaction_id = approval_data.get('interaction_id')
            interaction_timestamp = approval_data.get('interaction_timestamp')
            
            # Fallback: lookup conversation from DynamoDB if not in approval_data
            if not interaction_id or not interaction_timestamp:
                try:
                    timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=30)).timestamp())
                    response = interactions_table.scan(
                        FilterExpression='user_id = :uid AND #ts > :timeout AND awaiting_approval = :true',
                        ExpressionAttributeNames={'#ts': 'timestamp'},
                        ExpressionAttributeValues={
                            ':uid': approval_data['user_id'],
                            ':timeout': timeout_timestamp,
                            ':true': True
                        }
                    )
                    items = response.get('Items', [])
                    if items:
                        items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                        conv = items[0]
                        interaction_id = conv['interaction_id']
                        interaction_timestamp = conv['timestamp']
                        print(f"Found conversation via fallback lookup: {interaction_id}")
                except Exception as e:
                    print(f"Error in fallback lookup: {e}")
            
            if interaction_id and interaction_timestamp:
                update_conversation(
                    interaction_id,
                    interaction_timestamp,
                    f"DL request approved: {approval_data['distribution_list']}",
                    from_bot=True,
                    outcome='Resolved by Brie',
                    awaiting_approval=False
                )
            
            # Mark as completed in DynamoDB
            table.update_item(
                Key={'action_id': approval_id},
                UpdateExpression='SET #status = :status, updated_at = :updated',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'completed', ':updated': datetime.now().isoformat()}
            )
            
    elif action_id.startswith('deny_'):
        approval_id = action_id.replace('deny_', '')
        
        # Get from DynamoDB
        response = table.get_item(Key={'action_id': approval_id})
        if 'Item' in response:
            approval_data = response['Item']['details']
            
            # Notify user of denial
            denial_message = f"❌ Your request to join `{approval_data['distribution_list']}` has been denied. Please contact IT for more information."
            send_slack_message_to_channel({
                "channel": approval_data['user_id'],
                "text": denial_message
            })
            
            # Update conversation outcome if tracked
            if approval_data.get('interaction_id') and approval_data.get('interaction_timestamp'):
                update_conversation(
                    approval_data['interaction_id'],
                    approval_data['interaction_timestamp'],
                    f"DL request denied: {approval_data['distribution_list']}",
                    from_bot=True,
                    outcome='Escalated to IT',
                    awaiting_approval=False
                )
            
            # Mark as denied in DynamoDB
            table.update_item(
                Key={'action_id': approval_id},
                UpdateExpression='SET #status = :status, updated_at = :updated',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'denied', ':updated': datetime.now().isoformat()}
            )

def track_user_message(user_id, message, is_bot_response=False, image_url=None):
    """Track user's messages and bot responses for full conversation history"""
    if user_id not in user_conversations:
        user_conversations[user_id] = []
    
    message_entry = {
        'message': message,
        'timestamp': datetime.now().isoformat(),
        'is_bot': is_bot_response
    }
    
    # Add image URL if provided
    if image_url:
        message_entry['image_url'] = image_url
        message_entry['has_image'] = True
    
    user_conversations[user_id].append(message_entry)
    
    # Keep last 10 messages for full conversation context
    if len(user_conversations[user_id]) > 10:
        user_conversations[user_id] = user_conversations[user_id][-10:]

def get_conversation_context(user_id):
    """Get user's recent conversation for ticket context"""
    if user_id in user_conversations and user_conversations[user_id]:
        for msg in reversed(user_conversations[user_id]):
            if not msg['is_bot'] and not any(word in msg['message'].lower() for word in ['create ticket', 'ticket', 'escalate']):
                return msg['message']
    return None

def get_full_conversation_history(user_id):
    """Get complete conversation history for ticket"""
    if user_id not in user_conversations:
        return "No previous conversation history"
    
    conversation = []
    for msg in user_conversations[user_id]:
        if not any(word in msg['message'].lower() for word in ['create ticket', 'ticket', 'escalate']):
            if msg['is_bot']:
                conversation.append(f"Bot: {msg['message']}")
            else:
                if msg.get('has_image'):
                    conversation.append(f"User: {msg['message']} [SCREENSHOT: {msg.get('image_url', 'Image attached')}]")
                else:
                    conversation.append(f"User: {msg['message']}")
    
    return "\n\n".join(conversation) if conversation else "No previous conversation history"

def download_slack_image(image_url):
    """Download image from Slack and return base64 encoded data"""
    try:
        print(f"Attempting to download image from: {image_url}")
        headers = {'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
        req = urllib.request.Request(image_url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"Response status: {response.status}")
            if response.status == 200:
                image_data = response.read()
                print(f"Downloaded {len(image_data)} bytes")
                if len(image_data) > 0:
                    b64_data = base64.b64encode(image_data).decode('utf-8')
                    print(f"Encoded to base64: {len(b64_data)} characters")
                    return b64_data
                else:
                    print("Downloaded image is empty")
            else:
                print(f"HTTP error: {response.status}")
    except Exception as e:
        print(f"Error downloading image: {str(e)}")
    return None

def get_confluence_images_for_query(user_message, channel):
    """Search for relevant Confluence page and upload its images to Slack"""
    try:
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        # Search for pages matching the query
        search_query = urllib.parse.quote(f'label=foritchatbot AND text~"{user_message[:50]}"')
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/search?cql={search_query}&expand=body.storage&limit=1"
        
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        req.add_header('Accept', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            results = data.get('results', [])
            
            if not results:
                return 0
            
            page = results[0]
            page_id = page.get('id')
            content = page.get('body', {}).get('storage', {}).get('value', '')
            
            # Extract image filenames
            image_filenames = extract_confluence_images(content)
            
            if not image_filenames:
                return 0
            
            # Download and upload first 2 images (to avoid overwhelming the chat)
            uploaded_count = 0
            for filename in image_filenames[:2]:
                image_data = download_confluence_image(page_id, filename)
                if image_data:
                    if upload_image_to_slack(channel, image_data, filename):
                        uploaded_count += 1
                        print(f"Uploaded image: {filename}")
            
            return uploaded_count
            
    except Exception as e:
        print(f"Error getting Confluence images: {e}")
        return 0

def extract_confluence_images(html_content):
    """Extract image filenames from Confluence HTML"""
    import re
    images = []
    # Match Confluence image tags: <ac:image><ri:attachment ri:filename="image.png" /></ac:image>
    pattern = r'<ri:attachment ri:filename="([^"]+)"'
    matches = re.findall(pattern, html_content)
    return matches

def download_confluence_image(page_id, filename):
    """Download image from Confluence page"""
    try:
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        download_url = f"{CONFLUENCE_BASE_URL}/download/attachments/{page_id}/{urllib.parse.quote(filename)}"
        
        req = urllib.request.Request(download_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        
        # Follow redirects and download
        with urllib.request.urlopen(req) as response:
            return response.read()
    except Exception as e:
        print(f"Error downloading image {filename}: {e}")
        return None

def upload_image_to_slack(channel, image_data, filename):
    """Upload image to Slack channel"""
    try:
        url = "https://slack.com/api/files.upload"
        
        # Create multipart form data
        boundary = f"----WebKitFormBoundary{random.randint(1000000000, 9999999999)}"
        body = []
        
        # Add file data
        body.append(f'--{boundary}'.encode())
        body.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode())
        body.append(b'Content-Type: image/png')
        body.append(b'')
        body.append(image_data)
        
        # Add channels
        body.append(f'--{boundary}'.encode())
        body.append(b'Content-Disposition: form-data; name="channels"')
        body.append(b'')
        body.append(channel.encode())
        
        body.append(f'--{boundary}--'.encode())
        body_bytes = b'\r\n'.join(body)
        
        req = urllib.request.Request(url, data=body_bytes)
        req.add_header('Authorization', f'Bearer {SLACK_BOT_TOKEN}')
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('ok', False)
    except Exception as e:
        print(f"Error uploading image to Slack: {e}")
        return False

def get_confluence_content():
    """Fetch content from Confluence pages with foritchatbot label"""
    try:
        # Create authentication header
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        # Search for pages with foritchatbot label
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/search?cql=label=foritchatbot&expand=body.storage"
        
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        req.add_header('Accept', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            confluence_knowledge = []
            for page in data.get('results', []):
                title = page.get('title', '')
                content = page.get('body', {}).get('storage', {}).get('value', '')
                
                # Clean up HTML content (basic cleanup)
                import re
                clean_content = re.sub(r'<[^>]+>', '', content)
                clean_content = re.sub(r'\s+', ' ', clean_content).strip()
                
                confluence_knowledge.append(f"TITLE: {title}\nCONTENT: {clean_content}")
            
            return "\n\n---\n\n".join(confluence_knowledge)
            
    except Exception as e:
        print(f"Error fetching Confluence content: {e}")
        return ""

def send_slack_message(channel, text):
    """Send message to Slack using Web API"""
    try:
        url = 'https://slack.com/api/chat.postMessage'
        data = {
            'channel': channel,
            'text': text,
            'as_user': True
        }
        
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode('utf-8'), 
            headers=headers
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('ok', False)
            
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return False

def get_user_info_from_slack(user_id):
    """Get user name and email from Slack profile"""
    try:
        url = f'https://slack.com/api/users.info'
        data = {'user': user_id}
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data, headers=headers)
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            print(f"DEBUG - Full Slack API response: {json.dumps(result, indent=2)}")
            
            if result.get('ok') and 'user' in result:
                user_info = result['user']
                profile = user_info.get('profile', {})
                
                real_name = user_info.get('real_name', '') or profile.get('real_name', '') or profile.get('display_name', '')
                email = profile.get('email')
                
                print(f"DEBUG - profile.get('email'): {email}")
                print(f"DEBUG - real_name: {real_name}")
                
                if email and '@' in email:
                    print(f"Using email from Slack profile for user {user_id}: {email}")
                    return real_name, email
                else:
                    # Fallback: Generate email from real name
                    print(f"No email found for user {user_id}, generating from name")
                    if real_name and ' ' in real_name:
                        name_parts = real_name.strip().split()
                        first_name = name_parts[0].lower()
                        last_name = name_parts[-1].lower()
                        email = f"{first_name}.{last_name}@ever.ag"
                        print(f"Generated email: {email}")
                        return real_name, email
                    else:
                        print(f"Cannot generate email from name: {real_name}")
                        return real_name, None
            else:
                print(f"Failed to get user info: {result}")
                return None, None
                
    except Exception as e:
        print(f"Error getting user info: {e}")
        return None, None

def trigger_automation_workflow(user_email, user_name, message, channel, thread_ts, automation_type, user_id=None):
    """Trigger automation workflow via direct Lambda invocation"""
    try:
        import re
        lambda_client = boto3.client('lambda')
        
        # Strip Slack formatting from message before processing
        clean_message = re.sub(r'<mailto:([^|>]+)\|[^>]+>', r'\1', message)
        clean_message = re.sub(r'<([^|>]+)>', r'\1', clean_message)
        
        # Create email data for action processor
        email_data = {
            "sender": user_email,
            "subject": f"Automation Request from Slack: {user_name}",
            "body": clean_message,
            "messageId": f"slack_{channel}_{thread_ts}",
            "source": "it-helpdesk-bot",
            "slackContext": {
                "channel": channel,
                "thread_ts": thread_ts,
                "user_name": user_name,
                "user_id": user_id
            }
        }
        
        # Map automation type to action
        action_map = {
            'SSO_GROUP': 'AUTOMATE_SSO_GROUP',
            'DISTRIBUTION_LIST': 'AUTOMATE_DL_ACCESS',
            'SHARED_MAILBOX': 'AUTOMATE_MAILBOX_ACCESS'
        }
        
        action = action_map.get(automation_type, 'AUTOMATE_SSO_GROUP')
        
        # Step 1: Extract request details via action processor
        extract_response = lambda_client.invoke(
            FunctionName='it-action-processor',
            InvocationType='RequestResponse',  # Synchronous
            Payload=json.dumps({
                "emailData": email_data,
                "action": action
            })
        )
        
        extract_result = json.loads(extract_response['Payload'].read())
        print(f"Extract result: {extract_result}")
        
        if extract_result.get('statusCode') != 200:
            print(f"❌ Extraction failed: {extract_result}")
            return False
        
        # Get request details based on type
        if automation_type == 'SSO_GROUP':
            request_details = extract_result.get('ssoGroupRequest')
            if not request_details:
                print("❌ No SSO request extracted")
                return False
            
            # Query AD to find actual group name and check membership
            group_search = request_details.get('group_name', '')
            action = request_details.get('action', 'add')
            
            # First try: search with original term
            matches = query_group_type(group_search)
            
            # If no matches, strip keywords and try again
            if not matches:
                import re
                cleaned = re.sub(r'\b(sso|group|ad|active directory|distribution list|dl|single sign on|sign on)\b', '', group_search, flags=re.IGNORECASE).strip()
                if cleaned and cleaned != group_search:
                    print(f"No matches for '{group_search}', trying '{cleaned}'")
                    matches = query_group_type(cleaned)
            
            if not matches:
                send_slack_message(channel, f"❌ No groups found matching '{group_search}'")
                return False
            
            if len(matches) > 1:
                # Multiple matches - ask user to select
                group_list = "\n".join([f"• {g['name']}" for g in matches])
                send_slack_message(channel, f"🔍 Found multiple groups matching '{group_search}':\n\n{group_list}\n\nPlease reply with the exact group name you want.")
                
                # Store pending selection
                table = dynamodb.Table('it-actions')
                table.put_item(Item={
                    'action_id': f"pending_selection_{user_email}_{int(time.time())}",
                    'requester': user_email,
                    'status': 'PENDING_SELECTION',
                    'timestamp': int(time.time()),
                    'pending_selection': True,
                    'details': {
                        'similar_groups': [g['name'] for g in matches],
                        'action': action,
                        'channel': channel,
                        'thread_ts': thread_ts
                    }
                })
                return True
            
            # Single match - use exact group name
            exact_group = matches[0]['name']
            
            # Check membership
            membership_status = check_membership(user_email, exact_group)
            
            if membership_status == "ALREADY_MEMBER":
                send_slack_message(channel, f"ℹ️ You're already a member of **{exact_group}**.\n\nNo changes needed!")
                return True
            elif membership_status == "USER_NOT_FOUND":
                send_slack_message(channel, f"❌ Could not find your account in Active Directory. Please contact IT.")
                return False
            elif membership_status == "GROUP_NOT_FOUND":
                send_slack_message(channel, f"❌ Group **{exact_group}** not found in Active Directory.")
                return False
            
            # Update request with exact group name
            request_details['group_name'] = exact_group
            
            approval_response = lambda_client.invoke(
                FunctionName='it-approval-system',
                InvocationType='Event',
                Payload=json.dumps({
                    "action": "create_approval",
                    "approvalType": "SSO_GROUP",
                    "requester": user_email,
                    "ssoGroupRequest": request_details,
                    "emailData": email_data,
                    "details": f"User: {user_email}\nGroup: {exact_group}\nAction: {action}",
                    "callback_function": "brie-ad-group-manager",
                    "callback_params": {
                        "ssoGroupRequest": request_details,
                        "emailData": email_data
                    }
                })
            )
            return True
        else:
            # DL and Mailbox requests - check if approval was already sent
            body_str = extract_result.get('body', '{}')
            body = json.loads(body_str) if isinstance(body_str, str) else body_str
            
            # Check if approval was created (either directly or nested in result)
            if body.get('approval_id') or (body.get('result') and 'approval_id' in str(body.get('result'))):
                print(f"✅ Approval already sent by action-processor")
                return True
            
            # Check for sharedMailboxRequest (new format) - create approval
            shared_mailbox_request = extract_result.get('sharedMailboxRequest')
            if shared_mailbox_request:
                print(f"✅ Shared mailbox request extracted: {shared_mailbox_request}")
                
                # Create approval for shared mailbox
                users = shared_mailbox_request.get('users', [])
                mailboxes = shared_mailbox_request.get('shared_mailboxes', [])
                
                approval_response = lambda_client.invoke(
                    FunctionName='it-approval-system',
                    InvocationType='Event',
                    Payload=json.dumps({
                        "action": "create_approval",
                        "approvalType": "SHARED_MAILBOX",
                        "requester": user_email,
                        "emailData": email_data,
                        "details": f"User(s): {', '.join(users)}\nShared Mailbox(es): {', '.join(mailboxes)}",
                        "callback_function": "it-action-processor",
                        "callback_params": {
                            "sharedMailboxRequest": shared_mailbox_request,
                            "emailData": email_data
                        }
                    })
                )
                return True
            
            # Fallback: extract plan and send approval
            plan = extract_result.get('plan', {})
            if not plan:
                print("❌ No plan extracted")
                return False
            
            # Send approval request
            approval_response = lambda_client.invoke(
                FunctionName='it-approval-system',
                InvocationType='Event',
                Payload=json.dumps({
                    "action": "create_approval",
                    "approvalType": automation_type,
                    "requester": user_email,
                    "emailData": email_data,
                    "details": f"User(s): {', '.join(plan.get('users', []))}\nTarget(s): {', '.join([g.get('email', g.get('group_name', '')) for g in plan.get('groups', plan.get('mailboxes', []))])}",
                    "callback_function": "brie-infrastructure-connector",
                    "callback_params": {
                        "plan": plan,
                        "emailData": email_data
                    }
                })
            )
        
        print(f"✅ Approval request sent")
        return True
        
    except Exception as e:
        print(f"❌ Error triggering workflow: {e}")
        import traceback
        traceback.print_exc()
        return False

def log_interaction_to_dynamodb(user_id, user_name, user_message, bot_response):
    """Log interaction to Recent Interactions table - DISABLED: table does not exist"""
    # Legacy function - table 'recent-interactions' does not exist
    # Interactions are tracked in 'brie-it-helpdesk-bot-interactions' instead
    pass
    # try:
    #     table = dynamodb.Table('recent-interactions')
    #     table.put_item(Item={
    #         'user_id': user_id,
    #         'timestamp': int(time.time()),
    #         'user_name': user_name,
    #         'user_message': user_message,
    #         'bot_response': bot_response
    #     })
    # except Exception as e:
    #     print(f"Error logging interaction: {e}")

def save_ticket_to_dynamodb(user_id, user_name, user_email, interaction_id, timestamp):
    """Save ticket to DynamoDB and send email with conversation context"""
    try:
        table = dynamodb.Table('it-helpdesk-tickets')
        
        # Get conversation from DynamoDB
        response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
        if 'Item' not in response:
            return False
        
        item = response['Item']
        history = json.loads(item.get('conversation_history', '[]'))
        
        # Format conversation history
        conversation_lines = []
        issue_description = item.get('description', 'User requested support')
        for msg in history:
            message_text = msg['message']
            # Skip bot messages that contain ticket creation instructions
            if msg['from'] == 'bot' and ('create ticket' in message_text.lower() or 'itsupport@ever.ag' in message_text):
                continue
            from_label = "User" if msg['from'] == 'user' else "Brie"
            conversation_lines.append(f"{from_label}: {message_text}")
        
        conversation_history = "\n\n".join(conversation_lines) if conversation_lines else "No conversation history"
        
        ticket_timestamp = int(datetime.now().timestamp())
        ticket_id = f"{user_id}_{ticket_timestamp}"
        
        item = {
            'ticket_id': ticket_id,
            'user_id': user_id,
            'user_name': user_name,
            'user_email': user_email,
            'issue_description': issue_description,
            'conversation_history': conversation_history,
            'status': 'OPEN',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        table.put_item(Item=item)
        
        # Send email notification with full conversation history and images
        try:
            subject = issue_description
            
            # Enhanced email body with complete conversation
            body = f"""
New IT Support Request

Submitted by: {user_name}
Email: {user_email}

"""
            
            # Collect images from conversation
            attachments = []
            print(f"Checking for images in conversation for user {user_id}")
            if user_id in user_conversations:
                print(f"Found {len(user_conversations[user_id])} messages in conversation")
                for i, msg in enumerate(user_conversations[user_id]):
                    print(f"Message {i}: has_image={msg.get('has_image')}, image_url={msg.get('image_url')}")
                    if msg.get('has_image') and msg.get('image_url'):
                        print(f"Downloading image: {msg['image_url']}")
                        image_data = download_slack_image(msg['image_url'])
                        if image_data:
                            # Determine file extension from URL
                            file_ext = 'png'
                            if '.jpg' in msg['image_url'] or '.jpeg' in msg['image_url']:
                                file_ext = 'jpg'
                            elif '.gif' in msg['image_url']:
                                file_ext = 'gif'
                            
                            attachments.append({
                                'filename': f"screenshot_{i+1}.{file_ext}",
                                'data': image_data,
                                'content_type': f'image/{file_ext}'
                            })
                            print(f"Added attachment: screenshot_{i+1}.{file_ext}")
                        else:
                            print("Failed to download image data")
            else:
                print("No conversation history found for user")
            
            print(f"Total attachments: {len(attachments)}")
            
            if conversation_history and conversation_history != "No previous conversation history":
                body += f"""FULL CONVERSATION HISTORY:
{conversation_history}

Escalation Request: User requested ticket to be opened

End User Response: User tried suggested solutions but issue persists, requesting human support
"""
            else:
                body += f"""Issue Description: {issue_description}

Escalation Request: User requested ticket to be opened
"""
            
            body += f"""
Contact Information: {user_email}

This request was created via the IT Helpdesk Slack Bot.
Reply directly to this email to respond to the user.
            """
            
            # Send via SES with attachments
            if attachments:
                # Create multipart message with attachments
                msg = MIMEMultipart()
                msg['From'] = user_email
                msg['To'] = 'itsupport@ever.ag'
                msg['Subject'] = subject
                
                # Add body
                msg.attach(MIMEText(body, 'plain'))
                
                # Add attachments
                for attachment in attachments:
                    # Decode base64 to get raw image bytes
                    image_bytes = base64.b64decode(attachment['data'])
                    # Create proper image attachment
                    img = MIMEImage(image_bytes)
                    img.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{attachment["filename"]}"'
                    )
                    msg.attach(img)
                
                # Send email
                ses.send_raw_email(
                    Source=user_email,
                    Destinations=['itsupport@ever.ag'],
                    RawMessage={'Data': msg.as_string()}
                )
            else:
                # Send simple email without attachments
                ses.send_email(
                    Source=user_email,
                    Destination={'ToAddresses': ['itsupport@ever.ag']},
                    Message={
                        'Subject': {'Data': subject},
                        'Body': {'Text': {'Data': body}}
                    }
                )
        except Exception as e:
            print(f"Email error: {e}")
        
        return True
    except Exception as e:
        print(f"Error saving ticket: {e}")
        return False

def analyze_image_with_claude(image_url, user_message):
    """Analyze uploaded image using Claude Vision - copied from working Brie Agent"""
    try:
        print(f"Attempting to analyze image: {image_url}")
        
        # Download the image from Slack
        headers = {'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
        req = urllib.request.Request(image_url, headers=headers)
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status != 200:
                    print(f"HTTP error downloading image: {response.status}")
                    return "I can see you uploaded an image, but I'm having trouble downloading it from Slack. Please describe what the image shows."
                
                image_data = response.read()
                print(f"Successfully downloaded image, size: {len(image_data)} bytes")
                
                if len(image_data) == 0:
                    print("Downloaded image is empty")
                    return "The image appears to be empty. Please try uploading it again or describe what it shows."
                
        except urllib.error.HTTPError as e:
            print(f"HTTP error downloading image: {e.code} - {e.reason}")
            return "I can see you uploaded an image, but I don't have permission to access it. Please describe what the image shows."
        except Exception as e:
            print(f"Error downloading image: {e}")
            return "I can see you uploaded an image, but I'm having trouble downloading it. Please describe what the image shows."
        
        # Detect image format from magic bytes
        image_format = "image/png"  # default
        if image_data[:4] == b'\xff\xd8\xff\xe0' or image_data[:4] == b'\xff\xd8\xff\xe1':
            image_format = "image/jpeg"
        elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
            image_format = "image/png"
        elif image_data[:6] == b'GIF87a' or image_data[:6] == b'GIF89a':
            image_format = "image/gif"
        
        print(f"Detected image format: {image_format}, size: {len(image_data)} bytes")
        
        # Claude has a 5MB limit for images - if larger, we need to resize
        MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
        if len(image_data) > MAX_IMAGE_SIZE:
            print(f"Image too large ({len(image_data)} bytes), needs resizing")
            return "The image is too large to process. Please try uploading a smaller version or describe what it shows."
        
        # For very small images, also reject as they might be corrupted
        if len(image_data) < 1000:
            print(f"Image too small ({len(image_data)} bytes), might be corrupted")
            return "The image appears to be too small or corrupted. Please try uploading it again."
        
        # Convert image to base64 for Claude
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        print(f"Base64 encoded, length: {len(image_base64)}")
        
        # Prepare the request for Claude Vision (exact format from working Brie Agent)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_format,
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": f"""User message: {user_message}

Analyze this screenshot for IT support purposes. Extract:

1. Any error messages (exact text)
2. What application/system is shown
3. What the user is trying to do
4. Any visible UI problems or issues
5. Context that would help IT support

If it's a speed test, provide the download/upload speeds and ping.
If it's an error message, describe the error.
Focus on technical details that would help diagnose IT issues."""
                        }
                    ]
                }
            ]
        }
        
        print(f"Sending image to Claude for analysis...")
        
        response = bedrock.invoke_model(
            modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text']
        
        print(f"Claude analysis successful: {analysis[:100]}...")
        return analysis
        
    except Exception as e:
        print(f"Error analyzing image with Claude Vision: {e}")
        return "I can see you uploaded an image, but I'm having trouble analyzing it right now. Please describe what the image shows."

def get_claude_response(user_message, user_name, image_analysis=None):
    """Get response from Claude Sonnet 4 with Confluence knowledge and optional image analysis"""
    try:
        # Get Confluence content
        confluence_content = get_confluence_content()
        
        # Ever.Ag specific knowledge base
        company_info = f"""
Ever.Ag Company IT Information:

PASSWORD RESET:
- Call IT Support: 214-807-0784 (emergencies only)
- Or users can create a ticket by saying "create ticket"

IT SUPPORT CONTACT:
- Email: itsupport@ever.ag  
- Phone: 214-807-0784 (emergencies only)

GENERAL POLICIES:
- Company uses Microsoft Office 365
- Email domain: @ever.ag
- Standard business hours support

CONFLUENCE KNOWLEDGE BASE:
{confluence_content}
        """
        
        # Include image analysis if available
        message_content = f"User {user_name} asks: {user_message}"
        if image_analysis:
            message_content += f"\n\nImage Analysis: {image_analysis}"
        
        system_prompt = f"""You are an IT helpdesk assistant for Ever.Ag. You help employees with technical issues.

{company_info}

IMPORTANT INSTRUCTIONS:
1. Use the Confluence knowledge base above to provide accurate, company-specific troubleshooting steps
2. If image analysis is provided, incorporate those details into your response
3. For speed test results, comment on whether speeds are normal or concerning
4. If user asks about password reset, tell them to call 214-807-0784 (emergencies only) or say "create ticket"
5. For ticket creation, tell them to say "create ticket" 
6. Provide specific, actionable troubleshooting steps from the knowledge base
7. Be concise but helpful
8. Use emojis to make responses friendly
9. If you don't know something specific to Ever.Ag, provide general IT help and suggest contacting IT support

Always be helpful and professional. Reference the specific procedures from the Confluence documentation when applicable."""

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": message_content
                }
            ]
        }
        
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        claude_response = response_body['content'][0]['text']
        
        return claude_response
        
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return """I'm having trouble processing your request right now. 

For immediate help:
• **Password issues:** Call IT Support at 214-807-0784 (emergencies only)
• **Other IT issues:** Say "create ticket" to reach IT support
• **Email:** itsupport@ever.ag

I'll be back online shortly!"""

def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Handle approval notification from it-approval-system
        if event.get('approval_notification'):
            print("📥 Handling approval notification")
            approval_data = event.get('approval_data', {})
            slack_context = approval_data.get('slackContext', {})
            approver = approval_data.get('approver', 'IT Team')
            request_type = approval_data.get('request_type', 'Request')
            resource_name = approval_data.get('resource_name')
            
            print(f"Approver: {approver}, Request Type: {request_type}, Resource: {resource_name}")
            
            # Get user_id from slack context and look up active conversation
            user_id = slack_context.get('user_id')
            print(f"User ID: {user_id}")
            
            if user_id:
                try:
                    # Find active conversation for this user (In Progress or Awaiting Approval)
                    timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES)).timestamp())
                    print(f"Scanning for conversations after timestamp: {timeout_timestamp}")
                    
                    response = interactions_table.scan(
                        FilterExpression='user_id = :uid AND #ts > :timeout AND (outcome = :outcome1 OR outcome = :outcome2)',
                        ExpressionAttributeNames={'#ts': 'timestamp'},
                        ExpressionAttributeValues={
                            ':uid': user_id,
                            ':timeout': timeout_timestamp,
                            ':outcome1': 'In Progress',
                            ':outcome2': 'Awaiting Approval'
                        }
                    )
                    
                    items = response.get('Items', [])
                    print(f"Found {len(items)} active conversations")
                    
                    if items:
                        # Get most recent conversation
                        items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                        conv = items[0]
                        
                        # Extract resource from conversation history (more reliable than approval data)
                        import re
                        conv_hist = conv.get('conversation_history', '[]')
                        history = json.loads(conv_hist) if isinstance(conv_hist, str) else conv_hist
                        if isinstance(history, list) and len(history) > 0:
                            # Get first user message
                            first_msg = history[0].get('message', '')
                            # Extract all emails from message
                            emails = re.findall(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', first_msg)
                            # If we found any emails, use the first one as the resource
                            if emails:
                                resource_name = emails[0]
                                print(f"Extracted resource from conversation: {resource_name}")
                        
                        # Build approval message
                        if resource_name:
                            approval_message = f"{request_type} approved by {approver} for {resource_name}"
                        else:
                            approval_message = f"{request_type} approved by {approver}"
                        
                        print(f"Updating conversation: {conv['interaction_id']}")
                        
                        # Send Slack message to user
                        channel = slack_context.get('channel')
                        if channel:
                            send_slack_message(channel, f"✅ {approval_message}")
                        
                        update_conversation(
                            conv['interaction_id'],
                            conv['timestamp'],
                            approval_message,
                            from_bot=True,
                            outcome='Resolved by Brie',
                            awaiting_approval=False
                        )
                        print(f"✅ Updated conversation with approver: {approver}")
                    else:
                        print("⚠️ No active conversations found for user")
                except Exception as e:
                    print(f"⚠️ Error updating conversation: {e}")
                    import traceback
                    print(traceback.format_exc())
            else:
                print("⚠️ No user_id in slack context")
            
            return {'statusCode': 200, 'body': 'OK'}
        
        # Handle callback result from brie-ad-group-manager or other callback functions
        if event.get('callback_result'):
            print("📥 Handling callback result")
            result_data = event.get('result_data', {})
            slack_context = result_data.get('slackContext', {})
            message = result_data.get('message', '')
            
            user_id = slack_context.get('user_id')
            
            if user_id and message:
                try:
                    # Find active conversation
                    timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES)).timestamp())
                    response = interactions_table.scan(
                        FilterExpression='user_id = :uid AND #ts > :timeout',
                        ExpressionAttributeNames={'#ts': 'timestamp'},
                        ExpressionAttributeValues={
                            ':uid': user_id,
                            ':timeout': timeout_timestamp
                        }
                    )
                    
                    items = response.get('Items', [])
                    if items:
                        items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                        conv = items[0]
                        
                        # Track the callback message and mark as resolved
                        update_conversation(
                            conv['interaction_id'],
                            conv['timestamp'],
                            message,
                            from_bot=True,
                            outcome='Resolved by Brie',
                            awaiting_approval=False
                        )
                        print(f"✅ Tracked callback result in conversation and marked as resolved")
                except Exception as e:
                    print(f"⚠️ Error tracking callback result: {e}")
            
            return {'statusCode': 200, 'body': 'OK'}
        
        if 'body' in event:
            # Try to parse as JSON first
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                # Handle URL-encoded payloads (button clicks)
                if 'payload=' in event.get('body', ''):
                    parsed_body = urllib.parse.parse_qs(event['body'])
                    if 'payload' in parsed_body:
                        payload = json.loads(parsed_body['payload'][0])
                        
                        if payload.get('type') == 'block_actions':
                            action_id = payload.get('actions', [{}])[0].get('action_id', '')
                            user_id = payload.get('user', {}).get('id', '')
                            channel = payload.get('channel', {}).get('id', '')
                            
                            print(f"Button clicked: {action_id} by user {user_id}")
                            
                            if action_id.startswith(('approve_', 'deny_')):
                                handle_approval_response(action_id, user_id)
                                return {'statusCode': 200, 'body': 'OK'}
                            elif action_id.startswith(('resolved_', 'needhelp_', 'ticket_')):
                                handle_resolution_button(action_id, user_id, channel)
                                return {'statusCode': 200, 'body': 'OK'}
                
                return {'statusCode': 200, 'body': 'OK'}
            
            if body.get('type') == 'url_verification':
                return {
                    'statusCode': 200,
                    'headers': {'Content-Type': 'text/plain'},
                    'body': body['challenge']
                }
            
            # Handle interactive components (button clicks)
            if body.get('type') == 'interactive':
                payload = body.get('payload', {})
                if isinstance(payload, str):
                    payload = json.loads(payload)
                
                action_id = payload.get('actions', [{}])[0].get('action_id', '')
                user_id = payload.get('user', {}).get('id', '')
                
                if action_id.startswith(('approve_', 'deny_')):
                    handle_approval_response(action_id, user_id)
                    return {'statusCode': 200, 'body': 'OK'}
            
            # Handle interactive components (button clicks)
            if body.get('type') == 'interactive':
                payload = body.get('payload', {})
                if isinstance(payload, str):
                    payload = json.loads(payload)
                
                action_id = payload.get('actions', [{}])[0].get('action_id', '')
                user_id = payload.get('user', {}).get('id', '')
                
                if action_id.startswith(('approve_', 'deny_')):
                    handle_approval_response(action_id, user_id)
                    return {'statusCode': 200, 'body': 'OK'}
            
            if body.get('type') == 'event_callback':
                slack_event = body['event']
                
                # Comprehensive bot message filtering to prevent loops
                if (slack_event.get('subtype') == 'bot_message' or 
                    'bot_id' in slack_event or 
                    slack_event.get('user') == 'U09CEF9E5QB' or
                    slack_event.get('subtype') == 'message_changed' or
                    slack_event.get('subtype') == 'message_deleted'):
                    print(f"Ignoring bot/system message: {slack_event.get('subtype', 'bot_message')}")
                    return {'statusCode': 200, 'body': 'OK'}
                
                if slack_event['type'] == 'message':
                    user_id = slack_event.get('user')
                    real_name, user_email = get_user_info_from_slack(user_id)
                    user_name = real_name if real_name else f"user_{user_id}"
                    message = slack_event.get('text', '')
                    channel = slack_event.get('channel')
                    
                    # Track conversation
                    interaction_id, timestamp, is_new = get_or_create_conversation(user_id, user_name, message)
                    
                    # Check for Slack retries - ignore them to prevent duplicate processing
                    headers = event.get('headers', {})
                    if headers.get('X-Slack-Retry-Num') or headers.get('x-slack-retry-num'):
                        print(f"⚠️ Ignoring Slack retry: {headers.get('X-Slack-Retry-Num') or headers.get('x-slack-retry-num')}")
                        return {'statusCode': 200, 'body': 'OK'}
                    if not is_new:
                        # Update existing conversation
                        update_conversation(interaction_id, timestamp, message, from_bot=False)
                        # Check if user indicates resolution
                        if detect_resolution(message):
                            update_conversation(interaction_id, timestamp, message, from_bot=False, outcome='Self-Service Solution')
                        # Check if user indicates no further help needed
                        elif detect_no_further_help(message):
                            update_conversation(interaction_id, timestamp, "User indicated no further help needed", from_bot=False, outcome='Self-Service Solution')
                            return {'statusCode': 200, 'body': 'OK'}
                    
                    # Store for later use
                    user_interaction_ids[user_id] = {'interaction_id': interaction_id, 'timestamp': timestamp}
                    
                    # Log the full event for debugging
                    print(f"Full Slack event: {json.dumps(slack_event)}")
                    
                    # Check for image uploads in multiple possible locations
                    files = slack_event.get('files', [])
                    image_url = None
                    image_detected = False
                    
                    # Method 1: Direct files array
                    if files:
                        print(f"Found files array: {files}")
                        for file in files:
                            print(f"File details: {file}")
                            if file.get('mimetype', '').startswith('image/'):
                                image_detected = True
                                # Try original images first (better quality for Claude Vision), then thumbnails
                                for url_field in ['url_private', 'url_private_download', 'thumb_720', 'thumb_480', 'thumb_360']:
                                    if file.get(url_field):
                                        image_url = file[url_field]
                                        print(f"Found image URL via {url_field}: {image_url}")
                                        break
                                if image_url:
                                    break
                    
                    # Method 2: Check if this is a file_share subtype
                    if not image_url and slack_event.get('subtype') == 'file_share':
                        image_detected = True  # We know an image was shared
                        file_info = slack_event.get('file', {})
                        print(f"File share detected: {file_info}")
                        if file_info.get('mimetype', '').startswith('image/'):
                            # Try original images first (better quality for Claude Vision), then thumbnails
                            for url_field in ['url_private', 'url_private_download', 'thumb_720', 'thumb_480', 'thumb_360']:
                                if file_info.get(url_field):
                                    image_url = file_info[url_field]
                                    print(f"Found image URL via {url_field}: {image_url}")
                                    break
                    
                    # Method 3: Check attachments
                    if not image_url:
                        attachments = slack_event.get('attachments', [])
                        if attachments:
                            print(f"Found attachments: {attachments}")
                            for attachment in attachments:
                                if attachment.get('image_url'):
                                    image_detected = True
                                    image_url = attachment.get('image_url')
                                    print(f"Found image in attachments: {image_url}")
                                    break
                    
                    print(f"Processing message from {user_name}: {message}")
                    if image_url:
                        print(f"Image detected with URL: {image_url}")
                    elif image_detected:
                        print("Image detected but URL not accessible")
                    else:
                        print("No image detected in this message")
                    
                    # Track message for conversation context (include image URL if present)
                    if image_detected and image_url:
                        track_user_message(user_id, message, image_url=image_url)
                    else:
                        track_user_message(user_id, message)
                    message_lower = message.lower()
                    
                    # Check for ticket creation FIRST - don't process with Claude if creating ticket
                    if any(word in message_lower for word in ['create ticket', 'ticket', 'escalate', 'human support']):
                        real_name, user_email = get_user_info_from_slack(user_id)
                        
                        # Get full conversation history
                        conv_data = user_interaction_ids.get(user_id, {})
                        conversation_summary = None
                        if conv_data:
                            conversation_summary = get_conversation_summary(conv_data['interaction_id'], conv_data['timestamp'])
                        
                        # Use conversation summary instead of just previous question
                        ticket_context = conversation_summary if conversation_summary else get_conversation_context(user_id)
                        
                        if save_ticket_to_dynamodb(user_id, real_name, user_email, message, ticket_context):
                            response = f"""✅ **Support Request Submitted**

**Submitted by:** {real_name}
**From Email:** {user_email}
**Status:** Sent to itsupport@ever.ag"""
                            
                            if conversation_summary:
                                response += f"\n**Context:** Included full conversation history"
                            
                            response += "\n\nYour request has been submitted to IT Support.\nThey can reply directly to your email: " + user_email
                            
                            send_slack_message(channel, f"🔧 {response}")
                            
                            # Update conversation outcome
                            if conv_data:
                                update_conversation(conv_data['interaction_id'], conv_data['timestamp'], message, from_bot=False, outcome='Ticket Created')
                        else:
                            send_slack_message(channel, "🔧 ❌ Error submitting request. Please try again or call IT Support at 214-807-0784 (emergencies only).")
                        
                        # Return immediately - don't continue to Claude processing
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for software/subscription requests (NEW software purchases, not access to existing)
                    software_keywords = ['new software', 'request new software', 'purchase software', 'buy software',
                                       'software purchase', 'new subscription', 'request subscription', 
                                       'purchase subscription', 'buy subscription', 'new license',
                                       'purchase license', 'software license purchase']
                    if any(keyword in message_lower for keyword in software_keywords):
                        response = """📋 **Software & Subscription Requests**

For requesting new software or subscriptions, please fill out this form:
https://everag.gogenuity.com/help_center/workspaces/5806/forms/41983

**Important:**
• Add as much detail as possible in the form
• It's highly encouraged to have Finance approval before submitting
• We will send the request to the Cyber Security team for review

Need help with the form? Just ask!"""
                        send_slack_message(channel, response)
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check if user has a pending group selection
                    real_name, user_email = get_user_info_from_slack(user_id)
                    if user_email:
                        pending_selection = check_pending_group_selection(user_email)
                        
                        if pending_selection:
                            # User is responding to group selection prompt
                            details = pending_selection.get('details', {})
                            similar_groups = details.get('similar_groups', [])
                            selection_type = details.get('type', 'SSO_GROUP')
                            
                            # Check if message matches one of the similar groups
                            selected_group = None
                            for group in similar_groups:
                                if group.lower() == message.strip().lower():
                                    selected_group = group
                                    break
                            
                            if selected_group:
                                # Delete pending selection
                                table = dynamodb.Table('it-actions')
                                table.delete_item(Key={'action_id': pending_selection['action_id']})
                                
                                # Handle based on type
                                if selection_type == 'DISTRIBUTION_LIST':
                                    msg = f"✅ Got it! Requesting access to **{selected_group}**..."
                                    send_slack_message(channel, msg)
                                    
                                    # Track in conversation
                                    conv_data = user_interaction_ids.get(user_id, {})
                                    if conv_data:
                                        update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                                    
                                    # Send approval request
                                    send_approval_request(user_id, real_name, user_email, selected_group, f"Add me to the {selected_group} dl", conv_data)
                                    
                                    # Send approval confirmation message
                                    approval_msg = f"""📧 **Distribution List Request Received**

**Requested List:** `{selected_group}`
**Status:** Pending IT approval

I've sent your request to the IT team for approval. You'll be notified once they review it!"""
                                    
                                    send_slack_message(channel, approval_msg)
                                    if conv_data:
                                        update_conversation(conv_data['interaction_id'], conv_data['timestamp'], approval_msg, from_bot=True, outcome='Awaiting Approval', awaiting_approval=True)
                                    
                                    return {'statusCode': 200, 'body': 'OK'}
                                
                                # User selected a valid group - create new SSO request
                                send_slack_message(channel, f"✅ Got it! Requesting access to **{selected_group}**...")
                                
                                # Create SSO request directly with exact group name
                                lambda_client = boto3.client('lambda')
                                action = details.get('action', 'add')
                                
                                sso_request = {
                                    'user_email': user_email,
                                    'group_name': selected_group,  # Use exact group name
                                    'action': action,
                                    'requester': user_email
                                }
                                
                                email_data = {
                                    "sender": user_email,
                                    "subject": f"SSO Group Request from Slack: {real_name}",
                                    "body": f"{action} me to {selected_group}",
                                    "messageId": f"slack_{channel}_{slack_event.get('ts', '')}",
                                    "source": "it-helpdesk-bot",
                                    "slackContext": {
                                        "channel": channel,
                                        "thread_ts": slack_event.get('ts', ''),
                                        "user_name": real_name,
                                        "user_id": user_id
                                    }
                                }
                                
                                # Check if user is already a member before sending approval
                                membership_status = check_membership(user_email, selected_group)
                                
                                if membership_status == "ALREADY_MEMBER":
                                    send_slack_message(channel, f"ℹ️ You're already a member of **{selected_group}**. No action needed!")
                                    return {'statusCode': 200, 'body': 'OK'}
                                elif membership_status == "USER_NOT_FOUND":
                                    send_slack_message(channel, f"❌ Could not find your account in Active Directory. Please contact IT.")
                                    return {'statusCode': 200, 'body': 'OK'}
                                elif membership_status == "GROUP_NOT_FOUND":
                                    send_slack_message(channel, f"❌ Group **{selected_group}** not found in Active Directory.")
                                    return {'statusCode': 200, 'body': 'OK'}
                                elif membership_status == "ERROR":
                                    # If check fails, proceed with approval anyway (fail open)
                                    print(f"⚠️ Membership check failed, proceeding with approval")
                                
                                # Send approval request directly
                                approval_response = lambda_client.invoke(
                                    FunctionName='it-approval-system',
                                    InvocationType='Event',
                                    Payload=json.dumps({
                                        "action": "create_approval",
                                        "approvalType": "SSO_GROUP",
                                        "requester": user_email,
                                        "ssoGroupRequest": sso_request,
                                        "emailData": email_data,
                                        "details": f"User: {user_email}\nGroup: {selected_group}\nAction: {action}",
                                        "callback_function": "brie-ad-group-manager",
                                        "callback_params": {
                                            "ssoGroupRequest": sso_request,
                                            "emailData": email_data
                                        }
                                    })
                                )
                                
                                send_slack_message(channel, f"✅ Your request for **{selected_group}** is being processed. IT will review and approve shortly.")
                                return {'statusCode': 200, 'body': 'OK'}
                            else:
                                # Message doesn't match any of the options
                                send_slack_message(channel, f"❌ '{message}' doesn't match any of the suggested groups. Please reply with the exact group name from the list.")
                                return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for automation requests (DL, Mailbox, SSO) - NEW UNIFIED APPROACH
                    # Skip if message contains "dl" - will be handled by DL detection below
                    automation_type = None
                    if 'dl' not in message_lower and 'distribution list' not in message_lower:
                        automation_type = detect_automation_request(message)
                    
                    if automation_type:
                        real_name, user_email = get_user_info_from_slack(user_id)
                        
                        if not user_email:
                            send_slack_message(channel, "❌ Unable to retrieve your email address. Please contact IT directly.")
                            return {'statusCode': 200, 'body': 'OK'}
                    
                        # Check for recent duplicate requests (within last 60 seconds)
                        try:
                            table = dynamodb.Table('it-actions')
                            recent_cutoff = int(time.time()) - 60
                            response = table.query(
                                IndexName='requester-timestamp-index',
                                KeyConditionExpression='requester = :email AND #ts > :cutoff',
                                ExpressionAttributeNames={'#ts': 'timestamp'},
                                ExpressionAttributeValues={
                                    ':email': user_email,
                                    ':cutoff': recent_cutoff
                                }
                            )
                        
                            # Extract group name from current message
                            current_group = None
                            for match_type in ['sso_group', 'distribution_list', 'mailbox']:
                                if automation_type.get(match_type):
                                    current_group = automation_type[match_type].lower()
                                    break
                        
                            if current_group:
                                for item in response.get('Items', []):
                                    details = item.get('details', {})
                                    existing_group = details.get('group_name', '').lower()
                                    if existing_group and current_group in existing_group or existing_group in current_group:
                                        print(f"⚠️ Duplicate request detected for {current_group} within 60s, skipping")
                                        return {'statusCode': 200, 'body': 'OK'}
                        except Exception as e:
                            print(f"⚠️ Deduplication check failed: {e}, proceeding anyway")
                    
                        # Trigger Step Functions workflow with timeout message
                        import threading
                        result = [None]
                        
                        def run_workflow():
                            result[0] = trigger_automation_workflow(
                                user_email, 
                                real_name, 
                                message, 
                                channel, 
                                slack_event.get('ts', ''),
                                automation_type,
                                user_id
                            )
                        
                        thread = threading.Thread(target=run_workflow)
                        thread.start()
                        thread.join(timeout=3)
                        
                        if thread.is_alive():
                            send_slack_message(channel, "🔄 Processing your request... this may take up to 30 seconds.")
                            thread.join()
                        
                        execution_arn = result[0]
                        
                        if execution_arn:
                            msg = f"✅ Your {automation_type.replace('_', ' ').lower()} request is being processed. IT will review and approve shortly."
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True, outcome='Awaiting Approval', awaiting_approval=True)
                        else:
                            msg = "❌ Error processing your request. Please try again or contact IT directly."
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True)
                        
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # OLD DL CODE - DISABLED
                    elif False and any(word in message_lower for word in ['add me to', 'distribution list', 'distro list', 'email group']):
                        real_name, user_email = get_user_info_from_slack(user_id)
                        
                        # Send approval request with buttons to IT channel
                        approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
                        
                        # Store pending approval
                        pending_approvals[approval_id] = {
                            'user_id': user_id,
                            'user_name': real_name,
                            'user_email': user_email,
                            'message': message,
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        headers = {
                            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                            'Content-Type': 'application/json'
                        }
                        
                        approval_message = {
                            "channel": "C09KB40PL9J",
                            "text": f"Distribution List Access Request",
                            "blocks": [
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": f"*Distribution List Access Request*\n\n*User:* {real_name}\n*Email:* {user_email}\n*Message:* {message}"
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
                                            "action_id": f"approve_{approval_id}"
                                        },
                                        {
                                            "type": "button",
                                            "text": {
                                                "type": "plain_text",
                                                "text": "Deny"
                                            },
                                            "style": "danger",
                                            "action_id": f"deny_{approval_id}"
                                        }
                                    ]
                                }
                            ]
                        }
                        
                        data = json.dumps(approval_message).encode('utf-8')
                        
                        req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
                        
                        try:
                            with urllib.request.urlopen(req) as response:
                                result = json.loads(response.read().decode())
                                print(f"IT notification sent: {result}")
                        except Exception as e:
                            print(f"Error sending IT notification: {e}")
                        
                        # Respond to user
                        send_slack_message(channel, "📧 I've received your distribution list request and notified the IT team. They'll review it and get back to you!")
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for bulk distribution list updates (add/remove multiple people)
                    if is_bulk_distribution_list_update(message):
                        print(f"Bulk distribution list update detected: {message}")
                        real_name, user_email = get_user_info_from_slack(user_id)
                        
                        msg = "📋 I see you need to make multiple changes to a distribution list. I'll create a ticket for the IT team to handle this request."
                        send_slack_message(channel, msg)
                        update_conversation(interaction_id, timestamp, msg, from_bot=True)
                        
                        # Create ticket with full conversation history
                        if save_ticket_to_dynamodb(user_id, real_name, user_email, interaction_id, timestamp):
                            ticket_msg = f"✅ Ticket created with your distribution list update request. IT will follow up via email: {user_email}"
                            send_slack_message(channel, ticket_msg)
                            update_conversation(interaction_id, timestamp, ticket_msg, from_bot=True, outcome='Ticket Created')
                        else:
                            error_msg = "❌ Error creating ticket. Please try again or contact IT directly."
                            send_slack_message(channel, error_msg)
                            update_conversation(interaction_id, timestamp, error_msg, from_bot=True)
                        
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for distribution list requests
                    elif any(word in message_lower for word in ['add me to', 'distribution list', 'distro list', 'email group']):
                        print(f"Distribution list request detected: {message}")
                        real_name, user_email = get_user_info_from_slack(user_id)
                        distribution_list = extract_distribution_list_name(message)
                        
                        # If we couldn't extract a list name, ask user to clarify
                        if not distribution_list:
                            msg = "❌ I couldn't identify which distribution list you're referring to. Please specify the exact list name (e.g., 'Add me to the All Employees distribution list')"
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True)
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        # Search Exchange for matching DLs with timeout message
                        import threading
                        result = [None]
                        
                        def search_dls():
                            result[0] = query_group_type(distribution_list)
                        
                        thread = threading.Thread(target=search_dls)
                        thread.start()
                        thread.join(timeout=3)
                        
                        if thread.is_alive():
                            msg = "🔄 Searching for distribution lists... this may take up to 30 seconds."
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True)
                            thread.join()
                        
                        matches = result[0]
                        
                        if not matches:
                            msg = f"❌ No distribution lists found matching '{distribution_list}'"
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True)
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        # Filter to only show DLs
                        dl_matches = [m for m in matches if m['type'] == 'DISTRIBUTION_LIST']
                        
                        if not dl_matches:
                            msg = f"❌ No distribution lists found matching '{distribution_list}'. Found SSO groups instead - try 'add me to {distribution_list} sso group'"
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True)
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        if len(dl_matches) > 1:
                            # Multiple matches - ask user to select
                            group_list = "\n".join([f"• {g['name']}" for g in dl_matches])
                            msg = f"🔍 Found multiple distribution lists matching '{distribution_list}':\n\n{group_list}\n\nPlease reply with the exact list name you want."
                            send_slack_message(channel, msg)
                            update_conversation(interaction_id, timestamp, msg, from_bot=True)
                            
                            # Store pending selection
                            table = dynamodb.Table('it-actions')
                            table.put_item(Item={
                                'action_id': f"pending_selection_{user_email}_{int(time.time())}",
                                'requester': user_email,
                                'status': 'PENDING_SELECTION',
                                'timestamp': int(time.time()),
                                'pending_selection': True,
                                'details': {
                                    'similar_groups': [g['name'] for g in dl_matches],
                                    'action': 'add',
                                    'channel': channel,
                                    'thread_ts': slack_event.get('ts', ''),
                                    'type': 'DISTRIBUTION_LIST'
                                }
                            })
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        # Single match - use exact name
                        exact_dl = dl_matches[0]['name']
                        
                        # Get conversation data
                        conv_data = user_interaction_ids.get(user_id, {})
                        
                        # Send approval request
                        approval_id = send_approval_request(user_id, real_name, user_email, exact_dl, message, conv_data)
                        
                        response = f"""📧 **Distribution List Request Received**

**Requested List:** `{exact_dl}`
**Status:** Pending IT approval

I've sent your request to the IT team for approval. You'll be notified once they review it!"""
                        
                        send_slack_message(channel, response)
                        update_conversation(interaction_id, timestamp, response, from_bot=True, outcome='Awaiting Approval', awaiting_approval=True)
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    else:
                        # For Claude questions, send immediate response and return quickly to prevent retries
                        if image_detected:
                            if image_url:
                                send_slack_message(channel, "🔧 🤔 I can see you uploaded an image! Let me analyze it and get back to you...")
                            else:
                                send_slack_message(channel, "🔧 🤔 I can see you uploaded an image, but I'm having trouble accessing it. Let me help you anyway...")
                        else:
                            send_slack_message(channel, "🔧 🤔 Let me think about that... I'll have an answer for you in just a moment!")
                        
                        # Return immediately to Slack to prevent retries
                        # Then invoke async processing
                        lambda_client = boto3.client('lambda')
                        conv_data = user_interaction_ids.get(user_id, {})
                        async_payload = {
                            'async_processing': True,
                            'user_message': message,
                            'user_name': user_name,
                            'user_id': user_id,
                            'channel': channel,
                            'image_url': image_url,
                            'image_detected': image_detected,
                            'interaction_id': conv_data.get('interaction_id'),
                            'timestamp': int(conv_data.get('timestamp')) if conv_data.get('timestamp') else None
                        }
                        
                        # Start async processing but don't wait for it
                        try:
                            lambda_client.invoke(
                                FunctionName=context.function_name,
                                InvocationType='Event',  # Async invocation
                                Payload=json.dumps(async_payload)
                            )
                        except Exception as e:
                            print(f"Error invoking async processing: {e}")
                        
                        # Return immediately to prevent Slack retries
                        return {'statusCode': 200, 'body': 'OK'}
        
        # Handle engagement prompts
        elif event.get('engagement_prompt'):
            interaction_id = event['interaction_id']
            timestamp = event['timestamp']
            user_id = event.get('user_id')
            prompt_number = event.get('prompt_number', 1)
            
            # Check if still in progress and check last message time
            response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
            if 'Item' in response:
                item = response['Item']
                
                # Skip if not in progress or awaiting approval
                if item.get('outcome') != 'In Progress' or item.get('awaiting_approval'):
                    return {'statusCode': 200, 'body': 'OK'}
                
                # Check time since last message
                last_msg_time = item.get('last_message_timestamp', timestamp)
                last_msg_time = to_float(last_msg_time)
                time_since_last = datetime.utcnow().timestamp() - last_msg_time
                
                # Calculate expected delay based on prompt number
                expected_delay = prompt_number * 5 * 60  # 5 or 10 minutes
                
                # Only send prompt if enough time has passed since last message
                if time_since_last >= (expected_delay - 30):  # 30 second buffer
                    try:
                        # Open DM channel with user
                        req_data = json.dumps({'users': user_id}).encode('utf-8')
                        req = urllib.request.Request(
                            'https://slack.com/api/conversations.open',
                            data=req_data,
                            headers={
                                'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                                'Content-Type': 'application/json'
                            }
                        )
                        with urllib.request.urlopen(req) as response:
                            im_response = json.loads(response.read().decode('utf-8'))
                            channel = im_response.get('channel', {}).get('id')
                        
                        if channel:
                            issue_desc = item.get('description', 'your issue')
                            send_slack_message(channel, f"👋 Are you still there? Do you still need help with {issue_desc}?")
                            update_conversation(interaction_id, timestamp, f"Engagement prompt {prompt_number} sent", from_bot=True, update_last_message=False)
                            print(f"✅ Sent engagement prompt {prompt_number} for {interaction_id}")
                    except Exception as e:
                        print(f"Error sending engagement prompt: {e}")
            
            return {'statusCode': 200, 'body': 'OK'}
        
        # Handle auto-resolve after timeout
        elif event.get('auto_resolve'):
            interaction_id = event['interaction_id']
            timestamp = event['timestamp']
            user_id = event.get('user_id')
            
            # Check if still in progress (not already resolved by user)
            response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
            if 'Item' in response:
                item = response['Item']
                # Skip conversations awaiting approval
                if item.get('outcome') == 'In Progress' and not item.get('awaiting_approval'):
                    # Check time since last message
                    last_msg_time = item.get('last_message_timestamp', timestamp)
                    last_msg_time = to_float(last_msg_time)
                    time_since_last = datetime.utcnow().timestamp() - last_msg_time
                    
                    # Only auto-close if 15 minutes have passed since last message
                    if time_since_last >= (15 * 60 - 30):  # 30 second buffer
                        try:
                            req_data = json.dumps({'users': user_id}).encode('utf-8')
                            req = urllib.request.Request(
                                'https://slack.com/api/conversations.open',
                                data=req_data,
                                headers={
                                    'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                                    'Content-Type': 'application/json'
                                }
                            )
                            with urllib.request.urlopen(req) as response:
                                im_response = json.loads(response.read().decode('utf-8'))
                                channel = im_response.get('channel', {}).get('id')
                            
                            if channel:
                                send_slack_message(channel, "⏱️ Your session has timed out. Conversation closed.")
                        except Exception as e:
                            print(f"Error sending auto-close notification: {e}")
                        
                        # Auto-close with timeout status
                        update_conversation(interaction_id, timestamp, "Auto-closed due to inactivity (15 minutes)", from_bot=True, outcome='Timed Out - No Response')
                        print(f"✅ Auto-closed {interaction_id} due to timeout")
                    else:
                        print(f"⏭️ Skipped auto-close for {interaction_id} - recent activity detected")
                # Check for 7-day timeout on approval conversations
                elif item.get('outcome') == 'Awaiting Approval' and item.get('awaiting_approval'):
                    timestamp_val = to_float(timestamp)
                    conversation_age_days = (datetime.utcnow().timestamp() - timestamp_val) / 86400
                    if conversation_age_days >= 7:
                        # Escalate to ticket after 7 days
                        user_id = item.get('user_id')
                        
                        # Get user's DM channel
                        try:
                            req_data = json.dumps({'users': user_id}).encode('utf-8')
                            req = urllib.request.Request(
                                'https://slack.com/api/conversations.open',
                                data=req_data,
                                headers={
                                    'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                                    'Content-Type': 'application/json'
                                }
                            )
                            with urllib.request.urlopen(req) as response:
                                im_response = json.loads(response.read().decode('utf-8'))
                                channel = im_response.get('channel', {}).get('id')
                            
                            if channel:
                                send_slack_message(channel, "Your request has been waiting for approval for 7 days. A support ticket has been created for IT to follow up.")
                        except Exception as e:
                            print(f"Error sending escalation notification: {e}")
                        
                        # TODO: Create ticket using existing ticket system with conversation details
                        
                        update_conversation(interaction_id, timestamp, "Escalated to ticket after 7 days", from_bot=True, outcome='Escalated to Ticket', awaiting_approval=False)
                        print(f"✅ Escalated {interaction_id} to ticket after 7 days")
            
            return {'statusCode': 200, 'body': 'OK'}
        
        # Handle async processing
        elif event.get('async_processing'):
            user_message = event['user_message']
            user_name = event['user_name']
            channel = event['channel']
            user_id = event.get('user_id', 'unknown')
            image_url = event.get('image_url')
            image_detected = event.get('image_detected', False)
            interaction_id = event.get('interaction_id')
            timestamp = event.get('timestamp')
            
            print(f"Async processing for: {user_message}")
            
            # Send follow-up message
            time.sleep(8)
            
            image_analysis = None
            
            if image_url:
                followup_msg = "🤔 Still analyzing your image... Brie is examining the details!"
                send_slack_message(channel, followup_msg)
                
                # Analyze the image
                image_analysis = analyze_image_with_claude(image_url, user_message)
                print(f"Image analysis: {image_analysis}")
            elif image_detected:
                # Image was detected but URL not accessible
                followup_msg = "🤔 I can see you uploaded an image, but I'm having trouble accessing it. Let me help you anyway!"
                send_slack_message(channel, followup_msg)
                
                # Add a note about the image issue
                image_analysis = "User uploaded an image/screenshot but the bot couldn't access the file URL. Please ask the user to describe what the image shows so you can provide appropriate help."
            else:
                # Check if user mentioned uploading an image but we couldn't detect it
                if any(word in user_message.lower() for word in ['screenshot', 'image', 'picture', 'attached', 'upload']):
                    followup_msg = "🤔 I can see you mentioned an image, but I'm having trouble accessing it. Let me help you anyway!"
                    send_slack_message(channel, followup_msg)
                    
                    # Add a note about the image issue
                    image_analysis = "User mentioned uploading an image/screenshot but the bot couldn't detect or access the file. Ask user to describe what the image shows."
                else:
                    followup_msg = "🤔 Still working on your question... Brie is analyzing the best solution for you!"
                    send_slack_message(channel, followup_msg)
            
            # Get Claude response with Confluence knowledge and optional image analysis
            claude_response = get_claude_response(user_message, user_name, image_analysis)
            send_slack_message(channel, f"🔧 {claude_response}")
            
            # Try to upload relevant images from Confluence
            try:
                images_uploaded = get_confluence_images_for_query(user_message, channel)
                if images_uploaded > 0:
                    print(f"Uploaded {images_uploaded} images from Confluence")
            except Exception as e:
                print(f"Error uploading Confluence images: {e}")
            
            # Update conversation with bot response
            if interaction_id and timestamp:
                update_conversation(interaction_id, timestamp, claude_response, from_bot=True)
            
            # Track the bot's response in conversation history
            if image_analysis:
                full_response = f"{claude_response}\n\n[Image Analysis: {image_analysis}]"
                track_user_message(user_id, full_response, is_bot_response=True)
            else:
                track_user_message(user_id, claude_response, is_bot_response=True)
            
            # Log interaction to DynamoDB
            log_interaction_to_dynamodb(user_id, user_name, user_message, claude_response)
            
            print(f"Sent Claude response to Slack")
            
            # Send follow-up prompt with buttons after 3 seconds
            time.sleep(3)
            
            if interaction_id and timestamp:
                send_resolution_prompt(channel, user_id, interaction_id, timestamp)
        
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 200, 'body': 'OK'}
