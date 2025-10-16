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

# Helper to convert Decimal to int/float for JSON serialization
def decimal_to_number(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj
interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

# Conversation tracking
CONVERSATION_TIMEOUT_MINUTES = 30
user_conversations = {}  # {user_id: interaction_id}

def get_or_create_conversation(user_id, user_name, message_text):
    """Get existing conversation or create new one"""
    try:
        timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES)).timestamp())
        
        response = interactions_table.scan(
            FilterExpression='user_id = :uid AND #ts > :timeout',
            ExpressionAttributeNames={'#ts': 'timestamp'},
            ExpressionAttributeValues={':uid': user_id, ':timeout': timeout_timestamp}
        )
        
        items = response.get('Items', [])
        print(f"DEBUG: Found {len(items)} conversations within timeout window")
        if items:
            items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            active = items[0]
            print(f"DEBUG: Most recent conversation - ID: {active.get('interaction_id')}, Outcome: {active.get('outcome')}, Timestamp: {active.get('timestamp')}")
            # Check if conversation is still active (outcome is "In Progress")
            if active.get('outcome') == 'In Progress' and not active.get('awaiting_approval'):
                print(f"DEBUG: Returning active In Progress conversation")
                return active['interaction_id'], active['timestamp'], False, None
        
        # Check for recent timeouts (past 24 hours) with similar topics
        recent_timeout_timestamp = int((datetime.utcnow() - timedelta(hours=24)).timestamp())
        recent_response = interactions_table.scan(
            FilterExpression='user_id = :uid AND #ts > :recent AND outcome = :outcome',
            ExpressionAttributeNames={'#ts': 'timestamp'},
            ExpressionAttributeValues={
                ':uid': user_id, 
                ':recent': recent_timeout_timestamp,
                ':outcome': 'Timed Out - No Response'
            }
        )
        
        recent_items = recent_response.get('Items', [])
        if recent_items:
            recent_items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            for recent in recent_items:
                # Skip if awaiting approval
                if recent.get('awaiting_approval'):
                    continue
                # Check if there's already a pending resumption to avoid duplicates
                try:
                    actions_table = dynamodb.Table('it-actions')
                    pending_check = actions_table.scan(
                        FilterExpression='user_id = :uid AND action_type = :at',
                        ExpressionAttributeValues={':uid': user_id, ':at': 'pending_resumption'}
                    )
                    if pending_check.get('Items'):
                        print(f"DEBUG: Pending resumption already exists, skipping")
                        continue
                except Exception as e:
                    print(f"Error checking pending resumption: {e}")
                    continue
                # Compare topics using AI
                if compare_topics(message_text, recent.get('description', '')):
                    print(f"✅ Found related timeout conversation: {recent.get('interaction_id')}")
                    return None, None, True, recent
        
        print(f"DEBUG: Creating new conversation")
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
            'conversation_history': json.dumps([{'timestamp': datetime.utcnow().isoformat(), 'message': redacted_message, 'from': 'user'}]),
            'metadata': '{}'
        }
        
        interactions_table.put_item(Item=item)
        return interaction_id, timestamp, True, None
    except Exception as e:
        print(f"Error in conversation tracking: {e}")
        return None, 0, True, None

def compare_topics(new_message, previous_description):
    """Use simple keyword matching to determine if messages are related"""
    try:
        # Simple keyword-based matching for speed
        new_lower = new_message.lower()
        prev_lower = previous_description.lower()
        
        # Extract key nouns (simple approach)
        keywords = ['printer', 'excel', 'word', 'outlook', 'teams', 'vpn', 'password', 'laptop', 'monitor', 'keyboard', 'mouse', 'network', 'wifi', 'email', 'access', 'login']
        
        new_keywords = [k for k in keywords if k in new_lower]
        prev_keywords = [k for k in keywords if k in prev_lower]
        
        # If they share at least one keyword, consider them related
        return bool(set(new_keywords) & set(prev_keywords))
    except Exception as e:
        print(f"Error comparing topics: {e}")
        return False

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

def mark_conversation_awaiting_approval(interaction_id, timestamp):
    """Mark conversation as awaiting approval to exclude from timeouts"""
    try:
        interactions_table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp},
            UpdateExpression='SET awaiting_approval = :val, outcome = :outcome',
            ExpressionAttributeValues={':val': True, ':outcome': 'Awaiting Approval'}
        )
        print(f"✅ Marked {interaction_id} as awaiting approval")
    except Exception as e:
        print(f"Error marking conversation as awaiting approval: {e}")

def update_conversation(interaction_id, timestamp, message_text, from_bot=False, outcome=None):
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
        history.append({'timestamp': datetime.utcnow().isoformat(), 'message': redacted_message, 'from': 'bot' if from_bot else 'user'})
        
        update_expr = 'SET conversation_history = :hist, last_updated = :updated'
        expr_values = {':hist': json.dumps(history), ':updated': datetime.utcnow().isoformat()}
        
        if outcome:
            update_expr += ', outcome = :outcome'
            expr_values[':outcome'] = outcome
            # Cancel schedules when conversation is closed
            if outcome != 'In Progress':
                cancel_schedules(timestamp, interaction_id)
                print(f"✅ Cancelled schedules for closed conversation {interaction_id}")
        
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
    text = message_text.lower()
    resolved_phrases = ['thank', 'thanks', 'that worked', 'that fixed', 'that helped', 'resolved', 'solved', 'fixed', 'working now', 'all set', 'perfect', 'great', 'awesome', 'got it', 'that did it']
    return any(phrase in text for phrase in resolved_phrases)

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

def cancel_schedules(timestamp, interaction_id=None):
    """Cancel existing engagement and auto-resolve schedules"""
    try:
        scheduler_client = boto3.client('scheduler')
        # Use interaction_id if provided, otherwise use timestamp
        schedule_suffix = interaction_id if interaction_id else str(timestamp)
        for prefix in ['e5', 'e10', 'ar']:
            try:
                scheduler_client.delete_schedule(Name=f"{prefix}-{schedule_suffix}", GroupName='default')
                print(f"✅ Cancelled schedule {prefix}-{schedule_suffix}")
            except scheduler_client.exceptions.ResourceNotFoundException:
                print(f"⏭️ Schedule {prefix}-{schedule_suffix} not found (already deleted)")
            except Exception as e:
                print(f"❌ Error cancelling schedule {prefix}-{schedule_suffix}: {e}")
    except Exception as e:
        print(f"Error cancelling schedules: {e}")

def schedule_auto_resolve(interaction_id, timestamp, user_id):
    """Schedule engagement prompts at 5, 10 minutes and auto-resolve at 15 minutes"""
    try:
        # Convert Decimal to int if needed
        timestamp = decimal_to_number(timestamp)
        
        scheduler_client = boto3.client('scheduler')
        lambda_arn = f"arn:aws:lambda:us-east-1:843046951786:function:it-helpdesk-bot"
        role_arn = "arn:aws:iam::843046951786:role/EventBridgeSchedulerRole"
        
        # Schedule 5-minute engagement prompt
        schedule_time_5 = datetime.utcnow() + timedelta(minutes=5)
        try:
            scheduler_client.create_schedule(
                Name=f"e5-{timestamp}",
                ScheduleExpression=f"at({schedule_time_5.strftime('%Y-%m-%dT%H:%M:%S')})",
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
        except scheduler_client.exceptions.ConflictException:
            print(f"Schedule e5-{timestamp} already exists, skipping")
        
        # Schedule 10-minute engagement prompt
        schedule_time_10 = datetime.utcnow() + timedelta(minutes=10)
        try:
            scheduler_client.create_schedule(
                Name=f"e10-{timestamp}",
                ScheduleExpression=f"at({schedule_time_10.strftime('%Y-%m-%dT%H:%M:%S')})",
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
        except scheduler_client.exceptions.ConflictException:
            print(f"Schedule e10-{timestamp} already exists, skipping")
        
        # Schedule 15-minute auto-resolve
        schedule_time_15 = datetime.utcnow() + timedelta(minutes=15)
        try:
            scheduler_client.create_schedule(
                Name=f"ar-{timestamp}",
                ScheduleExpression=f"at({schedule_time_15.strftime('%Y-%m-%dT%H:%M:%S')})",
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
        except scheduler_client.exceptions.ConflictException:
            print(f"Schedule ar-{timestamp} already exists, skipping")
        
        print(f"✅ Scheduled engagement prompts (5, 10 min) and auto-resolve (15 min) for {interaction_id}")
    except Exception as e:
        print(f"Error scheduling engagement prompts: {e}")
        print(f"Error scheduling auto-resolve: {e}")

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
    if any(kw in text for kw in ['distribution list', 'dl ', 'shared mailbox', 'sso', 'access to']):
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
CONFLUENCE_API_TOKEN = os.environ.get('CONFLUENCE_API_TOKEN', 'your-confluence-token')
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
            FilterExpression='requester = :email AND #status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':email': user_email,
                ':status': 'PENDING_SELECTION'
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

def send_approval_request(user_id, user_name, user_email, distribution_list, original_message):
    """Send approval request to IT channel"""
    approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
    
    # Store approval data in DynamoDB
    actions_table = dynamodb.Table('it-actions')
    actions_table.put_item(Item={
        'action_id': approval_id,
        'user_id': user_id,
        'user_name': user_name,
        'user_email': user_email,
        'distribution_list': distribution_list,
        'original_message': original_message,
        'timestamp': int(datetime.now().timestamp()),
        'action_type': 'pending_approval'
    })
    
    # Create approval message with buttons
    approval_message = {
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
    send_slack_message(approval_message)
    
    return approval_id

def handle_approval_response(action_id, user_id):
    """Handle approval/denial response from IT team"""
    
    if action_id.startswith('approve_'):
        approval_id = action_id.replace('approve_', '')
        
        if approval_id in pending_approvals:
            approval_data = pending_approvals[approval_id]
            
            # Notify user of approval
            success_message = f"✅ Your distribution list request has been approved! Please contact IT to complete the process."
            
            headers = {
                'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                'Content-Type': 'application/json'
            }
            
            data = json.dumps({
                "channel": approval_data['user_id'],
                "text": success_message
            }).encode('utf-8')
            
            req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
            
            try:
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    print(f"Approval notification sent: {result}")
            except Exception as e:
                print(f"Error sending approval notification: {e}")
            
            # Clean up
            del pending_approvals[approval_id]
            
    elif action_id.startswith('deny_'):
        approval_id = action_id.replace('deny_', '')
        
        if approval_id in pending_approvals:
            approval_data = pending_approvals[approval_id]
            
            # Notify user of denial
            denial_message = f"❌ Your distribution list request has been denied. Please contact IT for more information."
            
            headers = {
                'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                'Content-Type': 'application/json'
            }
            
            data = json.dumps({
                "channel": approval_data['user_id'],
                "text": denial_message
            }).encode('utf-8')
            
            req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
            
            try:
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    print(f"Denial notification sent: {result}")
            except Exception as e:
                print(f"Error sending denial notification: {e}")
            
            # Clean up
            del pending_approvals[approval_id]

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
        r'add me to (?:the )?(.+?)\s+(?:dl|distribution list|distro list)',
        r'add me to (?:the )?(.+?)$',
        r'distribution list (.+?)$',
        r'distro list (.+?)$',
        r'mailing list (.+?)$',
        r'email group (.+?)$',
        r'access to (?:the )?(.+?)\s+(?:dl|distribution list|distro list)',
        r'access to (?:the )?(.+?)$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            return match.group(1).strip()
    
    return "IT email list"

def send_approval_request(user_id, user_name, user_email, distribution_list, original_message, conv_data=None):
    """Send approval request to IT channel"""
    approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
    
    # Store approval data in DynamoDB
    actions_table = dynamodb.Table('it-actions')
    actions_table.put_item(Item={
        'action_id': approval_id,
        'user_id': user_id,
        'user_name': user_name,
        'user_email': user_email,
        'distribution_list': distribution_list,
        'original_message': original_message,
        'timestamp': int(datetime.now().timestamp()),
        'action_type': 'pending_approval',
        'interaction_id': conv_data.get('interaction_id') if conv_data else None,
        'interaction_timestamp': conv_data.get('timestamp') if conv_data else None
    })
    
    # Create approval message with buttons
    approval_message = {
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
    
    if action_id.startswith('approve_'):
        approval_id = action_id.replace('approve_', '')
        
        # Get approval data from DynamoDB
        actions_table = dynamodb.Table('it-actions')
        response = actions_table.get_item(Key={'action_id': approval_id})
        
        if 'Item' in response:
            approval_data = response['Item']
            
            # Trigger it-action-processor to add user to DL
            try:
                lambda_client = boto3.client('lambda')
                processor_response = lambda_client.invoke(
                    FunctionName='it-action-processor',
                    InvocationType='RequestResponse',
                    Payload=json.dumps({
                        "emailData": {
                            "from": approval_data['user_email'],
                            "body": f"Please add me to the {approval_data['distribution_list']} distribution list"
                        },
                        "action": "AUTOMATE_DL_ACCESS"
                    })
                )
                
                result = json.loads(processor_response['Payload'].read())
                print(f"it-action-processor response: {result}")
                
                success_message = f"✅ Your request to join `{approval_data['distribution_list']}` has been approved and processed!"
            except Exception as e:
                print(f"Error invoking it-action-processor: {e}")
                success_message = f"✅ Your request to join `{approval_data['distribution_list']}` has been approved! Please contact IT to complete the process."
            
            # Notify user of approval
            send_slack_message_to_channel({
                "channel": approval_data['user_id'],
                "text": success_message
            })
            
            # Notify IT channel
            approver_name, _ = get_user_info_from_slack(user_id)
            approver_text = f" by {approver_name}" if approver_name else ""
            send_slack_message_to_channel({
                "channel": IT_APPROVAL_CHANNEL,
                "text": f"✅ Approved{approver_text}: {approval_data['user_name']} → `{approval_data['distribution_list']}`"
            })
            
            # Update conversation outcome if tracked
            if approval_data.get('interaction_id') and approval_data.get('interaction_timestamp'):
                approver_name, _ = get_user_info_from_slack(user_id)
                approver_text = f" by {approver_name}" if approver_name else ""
                update_conversation(
                    approval_data['interaction_id'],
                    approval_data['interaction_timestamp'],
                    f"DL request approved{approver_text}: {approval_data['distribution_list']}",
                    from_bot=True,
                    outcome='Resolved by Brie'
                )
            
            # Clean up
            actions_table.delete_item(Key={'action_id': approval_id})
            
    elif action_id.startswith('deny_'):
        approval_id = action_id.replace('deny_', '')
        
        # Get approval data from DynamoDB
        actions_table = dynamodb.Table('it-actions')
        response = actions_table.get_item(Key={'action_id': approval_id})
        
        if 'Item' in response:
            approval_data = response['Item']
            
            # Notify user of denial
            denial_message = f"❌ Your request to join `{approval_data['distribution_list']}` has been denied. Please contact IT for more information."
            send_slack_message_to_channel({
                "channel": approval_data['user_id'],
                "text": denial_message
            })
            
            # Clean up
            actions_table.delete_item(Key={'action_id': approval_id})

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

def get_confluence_images(page_id):
    """Get image attachments from a Confluence page"""
    try:
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
        
        url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/child/attachment"
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        req.add_header('Accept', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            images = []
            for attachment in data.get('results', []):
                if attachment.get('metadata', {}).get('mediaType', '').startswith('image/'):
                    images.append({
                        'title': attachment.get('title'),
                        'download_url': f"{CONFLUENCE_BASE_URL}{attachment['_links']['download']}"
                    })
            return images[:2]  # Limit to 2 images
    except Exception as e:
        print(f"Error getting Confluence images: {e}")
        return []

def upload_to_slack(channel, image_data, filename):
    """Upload image to Slack"""
    try:
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        body = []
        body.append(f'--{boundary}'.encode())
        body.append(f'Content-Disposition: form-data; name="channels"'.encode())
        body.append(b'')
        body.append(channel.encode())
        body.append(f'--{boundary}'.encode())
        body.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode())
        body.append(b'Content-Type: image/png')
        body.append(b'')
        body.append(base64.b64decode(image_data))
        body.append(f'--{boundary}--'.encode())
        body_bytes = b'\r\n'.join(body)
        
        req = urllib.request.Request('https://slack.com/api/files.upload', data=body_bytes)
        req.add_header('Authorization', f'Bearer {SLACK_BOT_TOKEN}')
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('ok', False)
    except Exception as e:
        print(f"Error uploading to Slack: {e}")
        return False

def send_slack_message(channel, text, blocks=None):
    """Send message to Slack using Web API"""
    try:
        url = 'https://slack.com/api/chat.postMessage'
        data = {
            'channel': channel,
            'text': text,
            'as_user': True
        }
        
        if blocks:
            data['blocks'] = blocks
        
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

def send_error_recovery_message(channel, error_msg, interaction_id, timestamp, user_id):
    """Send error message with recovery buttons"""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{error_msg}\n\nWhat would you like to do?"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🎫 Create Ticket", "emoji": True},
                    "action_id": f"error_ticket_{interaction_id}_{timestamp}",
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Start Over", "emoji": True},
                    "action_id": f"error_retry_{interaction_id}_{timestamp}"
                }
            ]
        }
    ]
    send_slack_message(channel, "", blocks=blocks)

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
            
            # Send progress message with 5-second delay
            import threading
            search_complete = threading.Event()
            
            def send_progress_message():
                if not search_complete.wait(5):
                    msg = "🔍 Still working on it..."
                    send_slack_message(channel, msg)
                    conv_data = user_interaction_ids.get(user_id, {})
                    if conv_data.get('interaction_id'):
                        update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
            
            progress_thread = threading.Thread(target=send_progress_message)
            progress_thread.start()
            
            # First try: search with original term
            matches = query_group_type(group_search)
            search_complete.set()
            
            # If no matches, strip keywords and try again
            if not matches:
                import re
                cleaned = re.sub(r'\b(sso|group|ad|active directory|distribution list|dl|single sign on|sign on)\b', '', group_search, flags=re.IGNORECASE).strip()
                if cleaned and cleaned != group_search:
                    print(f"No matches for '{group_search}', trying '{cleaned}'")
                    matches = query_group_type(cleaned)
            
            if not matches:
                msg = f"❌ No groups found matching '{group_search}'"
                # Log to conversation history
                conv_data = user_interaction_ids.get(user_id, {})
                if conv_data.get('interaction_id'):
                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                    send_error_recovery_message(channel, msg, conv_data['interaction_id'], conv_data['timestamp'], user_id)
                else:
                    send_slack_message(channel, msg)
                return False
            
            if len(matches) > 1:
                # Multiple matches - ask user to select
                group_list = "\n".join([f"• {g['name']}" for g in matches])
                msg = f"🔍 Found multiple groups matching '{group_search}':\n\n{group_list}\n\nPlease reply with the exact group name you want."
                send_slack_message(channel, msg)
                
                # Log to conversation history
                conv_data = user_interaction_ids.get(user_id, {})
                if conv_data.get('interaction_id'):
                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                
                # Store pending selection
                table = dynamodb.Table('it-actions')
                table.put_item(Item={
                    'action_id': f"pending_selection_{user_email}_{int(datetime.now().timestamp())}",
                    'requester': user_email,
                    'status': 'PENDING_SELECTION',
                    'timestamp': int(datetime.now().timestamp()),
                    'pending_selection': True,
                    'details': {
                        'similar_groups': [g['name'] for g in matches],
                        'action': action,
                        'channel': channel,
                        'thread_ts': thread_ts,
                        'user_id': user_id,
                        'automation_type': automation_type
                    }
                })
                return 'PENDING_SELECTION'
            
            # Single match - use exact group name
            exact_group = matches[0]['name']
            
            # Check membership
            membership_status = check_membership(user_email, exact_group)
            
            if membership_status == "ALREADY_MEMBER":
                msg = f"ℹ️ You're already a member of **{exact_group}**.\n\nNo changes needed!"
                send_slack_message(channel, msg)
                # Log to conversation history
                conv_data = user_interaction_ids.get(user_id, {})
                if conv_data.get('interaction_id'):
                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
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
    """Analyze uploaded image using Claude Vision"""
    try:
        print(f"Attempting to analyze image: {image_url}")
        
        # Try to download the image from Slack
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
                
                image_b64 = base64.b64encode(image_data).decode('utf-8')
                
        except urllib.error.HTTPError as e:
            print(f"HTTP error downloading image: {e.code} - {e.reason}")
            return "I can see you uploaded an image, but I don't have permission to access it. Please describe what the image shows."
        except Exception as e:
            print(f"Error downloading image: {e}")
            return "I can see you uploaded an image, but I'm having trouble downloading it. Please describe what the image shows."
        
        # Determine image type from URL or default to PNG
        if '.jpg' in image_url or '.jpeg' in image_url:
            media_type = "image/jpeg"
        elif '.png' in image_url:
            media_type = "image/png"
        elif '.gif' in image_url:
            media_type = "image/gif"
        elif '.webp' in image_url:
            media_type = "image/webp"
        else:
            media_type = "image/png"  # Default
        
        print(f"Using media type: {media_type}")
        
        # Prepare Claude Vision request
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"User message: {user_message}\n\nPlease analyze this image and extract any relevant technical information. If it's a speed test, provide the download/upload speeds and ping. If it's an error message, describe the error. If it's a network configuration, summarize the key details."
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64
                            }
                        }
                    ]
                }
            ]
        }
        
        print("Sending image to Claude for analysis...")
        
        # Call Claude Vision via Bedrock
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text']
        
        print(f"Claude analysis successful: {analysis[:100]}...")
        return analysis
        
    except Exception as e:
        print(f"Error analyzing image: {e}")
        error_msg = str(e)
        if "ValidationException" in error_msg:
            return "I can see you uploaded an image, but I'm having trouble processing it. This might be due to the image format or size. Please describe what the image shows so I can help you."
        elif "AccessDenied" in error_msg:
            return "I can see you uploaded an image, but I don't have permission to analyze it. Please describe what the image shows."
        else:
            return "I can see you uploaded an image, but I'm having trouble analyzing it right now. Please describe what the image shows."
        
        # Call Claude Vision via Bedrock
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text']
        
        return analysis
        
    except Exception as e:
        print(f"Error analyzing image: {e}")
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
        # Handle callback result from brie-ad-group-manager
        if event.get('callback_result'):
            result_data = event.get('result_data', {})
            slack_context = result_data.get('slackContext', {})
            message = result_data.get('message', '')
            status = result_data.get('status', '')
            user_id = slack_context.get('user_id')
            
            if user_id and message:
                # Find active conversation
                timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES)).timestamp())
                response = interactions_table.scan(
                    FilterExpression='user_id = :uid AND #ts > :timeout AND awaiting_approval = :awaiting',
                    ExpressionAttributeNames={'#ts': 'timestamp'},
                    ExpressionAttributeValues={
                        ':uid': user_id,
                        ':timeout': timeout_timestamp,
                        ':awaiting': True
                    }
                )
                
                items = response.get('Items', [])
                if items:
                    items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                    conv = items[0]
                    
                    # Update conversation based on status
                    if status == 'already_member':
                        update_conversation(conv['interaction_id'], conv['timestamp'], message, from_bot=True, outcome='Resolved by Brie')
                    elif status == 'failed':
                        update_conversation(conv['interaction_id'], conv['timestamp'], message, from_bot=True)
                    elif status == 'completed':
                        update_conversation(conv['interaction_id'], conv['timestamp'], message, from_bot=True)
            
            return {'statusCode': 200, 'body': 'OK'}
        
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
                    # Find active conversation for this user
                    timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES)).timestamp())
                    print(f"Scanning for conversations after timestamp: {timeout_timestamp}")
                    
                    response = interactions_table.scan(
                        FilterExpression='user_id = :uid AND #ts > :timeout AND awaiting_approval = :awaiting',
                        ExpressionAttributeNames={'#ts': 'timestamp'},
                        ExpressionAttributeValues={
                            ':uid': user_id,
                            ':timeout': timeout_timestamp,
                            ':awaiting': True
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
                        
                        update_conversation(
                            conv['interaction_id'],
                            conv['timestamp'],
                            approval_message,
                            from_bot=True,
                            outcome='Resolved by Brie'
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
                            elif action_id.startswith('engagement_'):
                                # Handle engagement prompt buttons
                                parts = action_id.split('_')
                                action_type = parts[1]  # yes, ticket, or resolved
                                interaction_id = parts[2]
                                timestamp = int(parts[3])
                                
                                if action_type == 'yes':
                                    # User still working on it
                                    send_slack_message(channel, "👍 No problem, take your time. Let me know if you need anything!")
                                    update_conversation(interaction_id, timestamp, "User confirmed still working on issue", from_bot=False)
                                    # Cancel old schedules and create new ones (keep original timestamp for conversation lookup)
                                    cancel_schedules(timestamp, interaction_id)
                                    schedule_auto_resolve(interaction_id, timestamp, user_id)
                                elif action_type == 'ticket':
                                    # Create ticket (reuse existing logic)
                                    handle_resolution_button(f"ticket_{interaction_id}_{timestamp}", user_id, channel)
                                elif action_type == 'resolved':
                                    # User is all set
                                    send_slack_message(channel, "✅ Great! Glad I could help. Feel free to reach out anytime!")
                                    cancel_schedules(timestamp, interaction_id)
                                    update_conversation(interaction_id, timestamp, "User confirmed issue resolved", from_bot=False, outcome='Self-Service Solution')
                                
                                return {'statusCode': 200, 'body': 'OK'}
                            elif action_id.startswith(('error_ticket_', 'error_retry_')):
                                # Handle error recovery buttons
                                parts = action_id.split('_')
                                action_type = parts[1]  # ticket or retry
                                interaction_id = parts[2]
                                timestamp = int(parts[3])
                                
                                if action_type == 'ticket':
                                    # Create ticket and close conversation
                                    send_slack_message(channel, "🎫 Creating a ticket for IT support...")
                                    cancel_schedules(timestamp, interaction_id)
                                    update_conversation(interaction_id, timestamp, "User requested ticket after error", from_bot=False, outcome='Ticket Created')
                                    handle_resolution_button(f"ticket_{interaction_id}_{timestamp}", user_id, channel)
                                elif action_type == 'retry':
                                    # Close conversation and allow fresh start
                                    send_slack_message(channel, "🔄 Okay, let's start fresh. What can I help you with?")
                                    cancel_schedules(timestamp, interaction_id)
                                    update_conversation(interaction_id, timestamp, "User chose to start over after error", from_bot=False, outcome='Cancelled - User Retry')
                                
                                return {'statusCode': 200, 'body': 'OK'}
                            elif action_id.startswith(('resumeyes_', 'resumeno_')):
                                # Handle resumption response
                                parts = action_id.split('_')
                                action_type = parts[0]  # resumeyes or resumeno
                                
                                # Get pending resumption data
                                actions_table = dynamodb.Table('it-actions')
                                pending_items = actions_table.scan(
                                    FilterExpression='user_id = :uid AND action_type = :at',
                                    ExpressionAttributeValues={':uid': user_id, ':at': 'pending_resumption'}
                                ).get('Items', [])
                                
                                if pending_items:
                                    pending = pending_items[0]
                                    old_interaction_id = pending['old_interaction_id']
                                    old_timestamp = pending['old_timestamp']
                                    new_message = pending['new_message']
                                    channel = pending['channel']
                                    
                                    # Delete pending resumption
                                    actions_table.delete_item(Key={'action_id': pending['action_id']})
                                    
                                    if action_type == 'resumeyes':
                                        # Resume old conversation
                                        send_slack_message(channel, "✅ Continuing your previous conversation...")
                                        update_conversation(old_interaction_id, old_timestamp, new_message, from_bot=False, outcome='In Progress')
                                        user_interaction_ids[user_id] = {'interaction_id': old_interaction_id, 'timestamp': old_timestamp}
                                        
                                        # Schedule engagement prompts
                                        cancel_schedules(old_timestamp, old_interaction_id)
                                        schedule_auto_resolve(old_interaction_id, old_timestamp, user_id)
                                        
                                        # Process the message with Claude
                                        real_name, _ = get_user_info_from_slack(user_id)
                                        user_name = real_name if real_name else f"user_{user_id}"
                                        
                                        send_slack_message(channel, "🔧 🤔 Let me think about that... I'll have an answer for you in just a moment!")
                                        
                                        lambda_client = boto3.client('lambda')
                                        async_payload = {
                                            'async_processing': True,
                                            'user_message': new_message,
                                            'user_name': user_name,
                                            'user_id': user_id,
                                            'channel': channel,
                                            'image_url': None,
                                            'image_detected': False,
                                            'interaction_id': old_interaction_id,
                                            'timestamp': int(old_timestamp)
                                        }
                                        lambda_client.invoke(
                                            FunctionName=context.function_name,
                                            InvocationType='Event',
                                            Payload=json.dumps(async_payload)
                                        )
                                    else:
                                        # Start new conversation
                                        send_slack_message(channel, "✅ Starting a new conversation...")
                                        real_name, _ = get_user_info_from_slack(user_id)
                                        user_name = real_name if real_name else f"user_{user_id}"
                                        
                                        # Create new conversation
                                        interaction_id = str(uuid.uuid4())
                                        timestamp = int(datetime.utcnow().timestamp())
                                        interaction_type = categorize_interaction(new_message)
                                        redacted_message = redact_sensitive_data(new_message)
                                        
                                        item = {
                                            'interaction_id': interaction_id,
                                            'timestamp': timestamp,
                                            'user_id': user_id,
                                            'user_name': user_name,
                                            'interaction_type': interaction_type,
                                            'description': redacted_message[:200],
                                            'outcome': 'In Progress',
                                            'date': datetime.utcnow().isoformat(),
                                            'conversation_history': json.dumps([{'timestamp': datetime.utcnow().isoformat(), 'message': redacted_message, 'from': 'user'}]),
                                            'metadata': '{}'
                                        }
                                        interactions_table.put_item(Item=item)
                                        user_interaction_ids[user_id] = {'interaction_id': interaction_id, 'timestamp': timestamp}
                                        
                                        send_slack_message(channel, "🔧 🤔 Let me think about that... I'll have an answer for you in just a moment!")
                                        
                                        lambda_client = boto3.client('lambda')
                                        async_payload = {
                                            'async_processing': True,
                                            'user_message': new_message,
                                            'user_name': user_name,
                                            'user_id': user_id,
                                            'channel': channel,
                                            'image_url': None,
                                            'image_detected': False,
                                            'interaction_id': interaction_id,
                                            'timestamp': timestamp
                                        }
                                        lambda_client.invoke(
                                            FunctionName=context.function_name,
                                            InvocationType='Event',
                                            Payload=json.dumps(async_payload)
                                        )
                                
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
                channel = payload.get('container', {}).get('channel_id', '')
                
                if action_id.startswith(('approve_', 'deny_')):
                    handle_approval_response(action_id, user_id)
                    return {'statusCode': 200, 'body': 'OK'}
                
                if action_id.startswith(('error_ticket_', 'error_retry_')):
                    # Handle error recovery buttons
                    parts = action_id.split('_')
                    action_type = parts[1]  # ticket or retry
                    interaction_id = parts[2]
                    timestamp = int(parts[3])
                    
                    if action_type == 'ticket':
                        # Create ticket and close conversation
                        send_slack_message(channel, "🎫 Creating a ticket for IT support...")
                        cancel_schedules(timestamp, interaction_id)
                        update_conversation(interaction_id, timestamp, "User requested ticket after error", from_bot=False, outcome='Ticket Created')
                        handle_resolution_button(f"ticket_{interaction_id}_{timestamp}", user_id, channel)
                    elif action_type == 'retry':
                        # Close conversation and allow fresh start
                        send_slack_message(channel, "🔄 Okay, let's start fresh. What can I help you with?")
                        cancel_schedules(timestamp, interaction_id)
                        update_conversation(interaction_id, timestamp, "User chose to start over after error", from_bot=False, outcome='Cancelled - User Retry')
                    
                    return {'statusCode': 200, 'body': 'OK'}
                
                if action_id.startswith(('resumeyes_', 'resumeno_')):
                    # Handle resumption response
                    parts = action_id.split('_')
                    action_type = parts[0]  # resumeyes or resumeno
                    user_id_from_action = parts[2]
                    prompt_ts = parts[3]
                    
                    # Get pending resumption data
                    actions_table = dynamodb.Table('it-actions')
                    pending_items = actions_table.scan(
                        FilterExpression='user_id = :uid AND action_type = :at',
                        ExpressionAttributeValues={':uid': user_id, ':at': 'pending_resumption'}
                    ).get('Items', [])
                    
                    if pending_items:
                        pending = pending_items[0]
                        old_interaction_id = pending['old_interaction_id']
                        old_timestamp = pending['old_timestamp']
                        new_message = pending['new_message']
                        channel = pending['channel']
                        
                        # Delete pending resumption
                        actions_table.delete_item(Key={'action_id': pending['action_id']})
                        
                        if action_type == 'resumeyes':
                            # Resume old conversation
                            send_slack_message(channel, "✅ Continuing your previous conversation...")
                            update_conversation(old_interaction_id, old_timestamp, new_message, from_bot=False, outcome='In Progress')
                            user_interaction_ids[user_id] = {'interaction_id': old_interaction_id, 'timestamp': old_timestamp}
                            
                            # Schedule engagement prompts
                            cancel_schedules(old_timestamp, old_interaction_id)
                            schedule_auto_resolve(old_interaction_id, old_timestamp, user_id)
                            
                            # Process the message with Claude
                            real_name, _ = get_user_info_from_slack(user_id)
                            user_name = real_name if real_name else f"user_{user_id}"
                            
                            send_slack_message(channel, "🔧 🤔 Let me think about that... I'll have an answer for you in just a moment!")
                            
                            lambda_client = boto3.client('lambda')
                            async_payload = {
                                'async_processing': True,
                                'user_message': new_message,
                                'user_name': user_name,
                                'user_id': user_id,
                                'channel': channel,
                                'image_url': None,
                                'image_detected': False,
                                'interaction_id': old_interaction_id,
                                'timestamp': int(old_timestamp)
                            }
                            lambda_client.invoke(
                                FunctionName=context.function_name,
                                InvocationType='Event',
                                Payload=json.dumps(async_payload)
                            )
                        else:
                            # Start new conversation
                            send_slack_message(channel, "✅ Starting a new conversation...")
                            real_name, _ = get_user_info_from_slack(user_id)
                            user_name = real_name if real_name else f"user_{user_id}"
                            
                            # Create new conversation
                            interaction_id = str(uuid.uuid4())
                            timestamp = int(datetime.utcnow().timestamp())
                            interaction_type = categorize_interaction(new_message)
                            redacted_message = redact_sensitive_data(new_message)
                            
                            item = {
                                'interaction_id': interaction_id,
                                'timestamp': timestamp,
                                'user_id': user_id,
                                'user_name': user_name,
                                'interaction_type': interaction_type,
                                'description': redacted_message[:200],
                                'outcome': 'In Progress',
                                'date': datetime.utcnow().isoformat(),
                                'conversation_history': json.dumps([{'timestamp': datetime.utcnow().isoformat(), 'message': redacted_message, 'from': 'user'}]),
                                'metadata': '{}'
                            }
                            interactions_table.put_item(Item=item)
                            user_interaction_ids[user_id] = {'interaction_id': interaction_id, 'timestamp': timestamp}
                            
                            send_slack_message(channel, "🔧 🤔 Let me think about that... I'll have an answer for you in just a moment!")
                            
                            lambda_client = boto3.client('lambda')
                            async_payload = {
                                'async_processing': True,
                                'user_message': new_message,
                                'user_name': user_name,
                                'user_id': user_id,
                                'channel': channel,
                                'image_url': None,
                                'image_detected': False,
                                'interaction_id': interaction_id,
                                'timestamp': timestamp
                            }
                            lambda_client.invoke(
                                FunctionName=context.function_name,
                                InvocationType='Event',
                                Payload=json.dumps(async_payload)
                            )
                    
                    return {'statusCode': 200, 'body': 'OK'}
            
            if body.get('type') == 'event_callback':
                # Check for Slack retries - ignore them to prevent duplicate processing
                headers = event.get('headers', {})
                if headers.get('X-Slack-Retry-Num') or headers.get('x-slack-retry-num'):
                    print(f"⚠️ Ignoring Slack retry: {headers.get('X-Slack-Retry-Num') or headers.get('x-slack-retry-num')}")
                    return {'statusCode': 200, 'body': 'OK'}
                
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
                    
                    # Send immediate acknowledgment
                    send_slack_message(channel, "🔍 Checking your request...")
                    
                    # Check if user has pending group selection
                    actions_table = dynamodb.Table('it-actions')
                    pending_items = actions_table.scan(
                        FilterExpression='requester = :email AND #status = :status',
                        ExpressionAttributeNames={'#status': 'status'},
                        ExpressionAttributeValues={':email': user_email, ':status': 'PENDING_SELECTION'}
                    ).get('Items', [])
                    
                    if pending_items:
                        pending = pending_items[0]
                        similar_groups = pending['details']['similar_groups']
                        
                        # Check if user's message matches one of the groups
                        # Strip Slack link formatting: <http://ever.ag|ever.ag> -> ever.ag
                        import re
                        user_selection = message.strip()
                        print(f"DEBUG: Original message: {user_selection}")
                        user_selection = re.sub(r'<http[s]?://([^|>]+)\|([^>]+)>', r'\2', user_selection)
                        user_selection = re.sub(r'<http[s]?://([^>]+)>', r'\1', user_selection)
                        print(f"DEBUG: After stripping links: {user_selection}")
                        
                        # Try exact match first
                        matched_group = None
                        if user_selection in similar_groups:
                            matched_group = user_selection
                        else:
                            # Try case-insensitive match
                            user_lower = user_selection.lower()
                            for group in similar_groups:
                                if group.lower() == user_lower:
                                    matched_group = group
                                    break
                        
                        print(f"DEBUG: Matched group: {matched_group}")
                        
                        if matched_group:
                            # User selected a valid group
                            send_slack_message(channel, f"✅ Got it! Processing your request for **{matched_group}**...")
                            
                            # Delete pending selection
                            actions_table.delete_item(Key={'action_id': pending['action_id']})
                            
                            # Check request type
                            request_type = pending['details'].get('type', 'SSO_GROUP')
                            
                            if request_type == 'DISTRIBUTION_LIST':
                                # Handle DL request
                                conv_data = user_interaction_ids.get(user_id, {})
                                approval_id = send_approval_request(user_id, user_name, user_email, matched_group, f"add me to {matched_group}", conv_data)
                                
                                if conv_data.get('interaction_id'):
                                    mark_conversation_awaiting_approval(conv_data['interaction_id'], conv_data['timestamp'])
                                
                                msg = f"✅ Your request for **{matched_group}** is being processed. IT will review and approve shortly.\n\nWhile IT reviews this, I can still help you with other needs. Just ask!"
                                send_slack_message(channel, msg)
                                
                                if conv_data.get('interaction_id'):
                                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                                
                                return {'statusCode': 200, 'body': 'OK'}
                            
                            # Handle SSO group request
                            lambda_client = boto3.client('lambda')
                            
                            request_details = {
                                'user_email': user_email,
                                'group_name': matched_group,
                                'action': 'add',
                                'requester': user_email
                            }
                            
                            email_data = {
                                'sender': user_email,
                                'subject': f'SSO Group Access Request: {matched_group}',
                                'body': f'User {user_name} ({user_email}) requests access to {matched_group}',
                                'messageId': f'slack_{channel}_{int(datetime.utcnow().timestamp())}',
                                'source': 'it-helpdesk-bot'
                            }
                            
                            approval_response = lambda_client.invoke(
                                FunctionName='it-approval-system',
                                InvocationType='Event',
                                Payload=json.dumps({
                                    "action": "create_approval",
                                    "approvalType": "SSO_GROUP",
                                    "requester": user_email,
                                    "ssoGroupRequest": request_details,
                                    "emailData": email_data,
                                    "details": f"User: {user_email}\nGroup: {matched_group}\nAction: add",
                                    "callback_function": "brie-ad-group-manager",
                                    "callback_params": {
                                        "ssoGroupRequest": request_details,
                                        "emailData": email_data
                                    }
                                })
                            )
                            
                            # Mark conversation as awaiting approval
                            conv_data = user_interaction_ids.get(user_id, {})
                            if conv_data.get('interaction_id'):
                                mark_conversation_awaiting_approval(conv_data['interaction_id'], conv_data['timestamp'])
                                
                                # Create SSO interaction tracking for callback
                                print(f"📝 Creating SSO interaction tracking for {conv_data['interaction_id']}")
                                tracking_id = f"sso_tracking_{user_id}_{int(datetime.utcnow().timestamp())}"
                                actions_table.put_item(Item={
                                    'action_id': tracking_id,
                                    'action_type': 'sso_interaction_tracking',
                                    'interaction_id': conv_data['interaction_id'],
                                    'interaction_timestamp': conv_data['timestamp'],
                                    'user_email': user_email,
                                    'group_name': matched_group,
                                    'timestamp': int(datetime.utcnow().timestamp())
                                })
                                print(f"✅ Created tracking record: {tracking_id}")
                            
                            msg = f"✅ Your SSO group request is being processed. IT will review and approve shortly.\n\nWhile IT reviews this, I can still help you with other needs. Just ask!"
                            send_slack_message(channel, msg)
                            
                            if conv_data.get('interaction_id'):
                                update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                            
                            return {'statusCode': 200, 'body': 'OK'}
                        else:
                            # Invalid selection
                            send_slack_message(channel, f"❌ '{user_selection}' doesn't match any of the groups I showed you. Please reply with the exact group name from the list.")
                            return {'statusCode': 200, 'body': 'OK'}
                    
                    # Track conversation
                    interaction_id, timestamp, is_new, resumption_conv = get_or_create_conversation(user_id, user_name, message)
                    
                    # Check if resumption prompt is needed
                    if resumption_conv:
                        # Show resumption prompt
                        old_description = resumption_conv.get('description', 'your previous issue')
                        prompt_ts = int(datetime.utcnow().timestamp())
                        
                        blocks = [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f":wave: Welcome back! I see you had a previous conversation about:\n\n> {old_description}\n\nIs your new message related to this issue?"
                                }
                            },
                            {
                                "type": "actions",
                                "elements": [
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": ":white_check_mark: Yes, same issue", "emoji": True},
                                        "action_id": f"resumeyes_pending_{user_id}_{prompt_ts}",
                                        "style": "primary"
                                    },
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": ":x: No, different issue", "emoji": True},
                                        "action_id": f"resumeno_pending_{user_id}_{prompt_ts}"
                                    }
                                ]
                            }
                        ]
                        
                        send_slack_message(channel, "", blocks=blocks)
                        
                        # Store pending resumption
                        actions_table = dynamodb.Table('it-actions')
                        actions_table.put_item(Item={
                            'action_id': f"pending_resumption_{user_id}_{prompt_ts}",
                            'user_id': user_id,
                            'action_type': 'pending_resumption',
                            'timestamp': prompt_ts,
                            'old_interaction_id': resumption_conv['interaction_id'],
                            'old_timestamp': resumption_conv['timestamp'],
                            'new_message': message,
                            'channel': channel
                        })
                        
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    if not is_new:
                        # Update existing conversation
                        update_conversation(interaction_id, timestamp, message, from_bot=False)
                        
                        # Cancel existing schedules and create new ones (keep original timestamp)
                        cancel_schedules(timestamp, interaction_id)
                        schedule_auto_resolve(interaction_id, timestamp, user_id)
                        
                        # Check if user indicates resolution
                        if detect_resolution(message):
                            cancel_schedules(timestamp, interaction_id)
                            update_conversation(interaction_id, timestamp, message, from_bot=False, outcome='Self-Service Solution')
                    
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
                                # Try thumbnail URLs first (more likely to be accessible), then private URLs
                                for url_field in ['thumb_720', 'thumb_480', 'thumb_360', 'permalink_public', 'url_private_download', 'url_private']:
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
                            # Try thumbnail URLs first (more likely to be accessible), then private URLs
                            for url_field in ['thumb_720', 'thumb_480', 'thumb_360', 'permalink_public', 'url_private_download', 'url_private']:
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
                        print(f"DEBUG - Pending selection for {user_email}: {pending_selection}")
                        
                        if pending_selection:
                            # User is responding to group selection prompt
                            details = pending_selection.get('details', {})
                            similar_groups = details.get('similar_groups', [])
                            
                            # Check if message matches one of the similar groups
                            selected_group = None
                            for group in similar_groups:
                                if group.lower() == message.strip().lower():
                                    selected_group = group
                                    break
                            
                            if selected_group:
                                # User selected a valid group
                                msg = f"✅ Got it! Requesting access to **{selected_group}**..."
                                send_slack_message(channel, msg)
                                
                                # Log to conversation history
                                conv_data = user_interaction_ids.get(user_id, {})
                                if conv_data.get('interaction_id'):
                                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                                
                                # Delete pending selection
                                table = dynamodb.Table('it-actions')
                                table.delete_item(Key={'action_id': pending_selection['action_id']})
                                
                                action = details.get('action', 'add')
                                request_type = details.get('type', 'SSO_GROUP')
                                
                                # Handle based on type
                                if request_type == 'DISTRIBUTION_LIST':
                                    # Get conversation data
                                    conv_data = user_interaction_ids.get(user_id, {})
                                    
                                    # Send DL approval
                                    approval_id = send_approval_request(user_id, real_name, user_email, selected_group, f"add me to {selected_group}", conv_data)
                                    
                                    # Mark conversation as awaiting approval
                                    if conv_data.get('interaction_id'):
                                        mark_conversation_awaiting_approval(conv_data['interaction_id'], conv_data['timestamp'])
                                    
                                    msg = f"✅ Your request for **{selected_group}** is being processed. IT will review and approve shortly.\n\nWhile IT reviews this, I can still help you with other needs. Just ask!"
                                    send_slack_message(channel, msg)
                                    
                                    # Log to conversation history
                                    if conv_data.get('interaction_id'):
                                        update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                                    
                                    return {'statusCode': 200, 'body': 'OK'}
                                
                                # SSO Group handling
                                lambda_client = boto3.client('lambda')
                                
                                sso_request = {
                                    'user_email': user_email,
                                    'group_name': selected_group,
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
                                conv_data = user_interaction_ids.get(user_id, {})
                                
                                # Store interaction tracking for this approval
                                if conv_data.get('interaction_id'):
                                    actions_table = dynamodb.Table('it-actions')
                                    tracking_id = f"sso_tracking_{user_id}_{int(datetime.now().timestamp())}"
                                    actions_table.put_item(Item={
                                        'action_id': tracking_id,
                                        'action_type': 'sso_interaction_tracking',
                                        'interaction_id': conv_data['interaction_id'],
                                        'interaction_timestamp': conv_data['timestamp'],
                                        'user_email': user_email,
                                        'group_name': selected_group,
                                        'timestamp': int(datetime.now().timestamp())
                                    })
                                
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
                                            "emailData": email_data,
                                            "interaction_id": conv_data.get('interaction_id'),
                                            "interaction_timestamp": conv_data.get('timestamp')
                                        }
                                    })
                                )
                                
                                # Mark conversation as awaiting approval
                                if conv_data.get('interaction_id'):
                                    print(f"🔵 SSO PATH: Marking conversation as awaiting approval")
                                    mark_conversation_awaiting_approval(conv_data['interaction_id'], conv_data['timestamp'])
                                
                                msg = f"✅ Your request for **{selected_group}** is being processed. IT will review and approve shortly.\n\nWhile IT reviews this, I can still help you with other needs. Just ask!"
                                print(f"🔵 SSO PATH: Sending approval message to Slack")
                                send_slack_message(channel, msg)
                                
                                # Log to conversation history
                                if conv_data.get('interaction_id'):
                                    print(f"📝 Adding approval message to conversation history: {conv_data['interaction_id']}")
                                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                                    print(f"✅ Approval message added to conversation history")
                                else:
                                    print(f"⚠️ No interaction_id found in conv_data for SSO approval message")
                                
                                return {'statusCode': 200, 'body': 'OK'}
                            else:
                                # Message doesn't match any of the options
                                send_slack_message(channel, f"❌ '{message}' doesn't match any of the suggested groups. Please reply with the exact group name from the list.")
                                return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for automation requests (DL, Mailbox, SSO) - NEW UNIFIED APPROACH
                    automation_type = None
                    if 'dl' not in message_lower and 'distribution list' not in message_lower:
                        automation_type = detect_automation_request(message)
                    
                    if automation_type:
                        real_name, user_email = get_user_info_from_slack(user_id)
                        
                        if not user_email:
                            send_slack_message(channel, "❌ Unable to retrieve your email address. Please contact IT directly.")
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        # Trigger Step Functions workflow
                        execution_arn = trigger_automation_workflow(
                            user_email, 
                            real_name, 
                            message, 
                            channel, 
                            slack_event.get('ts', ''),
                            automation_type,
                            user_id
                        )
                        
                        if execution_arn == 'PENDING_SELECTION':
                            # User needs to select from multiple groups - don't mark as awaiting approval yet
                            print(f"⏳ Waiting for user to select from multiple groups")
                            return {'statusCode': 200, 'body': 'OK'}
                        elif execution_arn:
                            # Mark conversation as awaiting approval
                            conv_data = user_interaction_ids.get(user_id, {})
                            if conv_data.get('interaction_id'):
                                mark_conversation_awaiting_approval(conv_data['interaction_id'], conv_data['timestamp'])
                                
                                # Store interaction tracking for SSO approvals
                                if automation_type == 'SSO_GROUP':
                                    print(f"📝 Creating SSO interaction tracking for {conv_data['interaction_id']}")
                                    actions_table = dynamodb.Table('it-actions')
                                    tracking_id = f"sso_tracking_{user_id}_{int(datetime.now().timestamp())}"
                                    actions_table.put_item(Item={
                                        'action_id': tracking_id,
                                        'action_type': 'sso_interaction_tracking',
                                        'interaction_id': conv_data['interaction_id'],
                                        'interaction_timestamp': conv_data['timestamp'],
                                        'user_email': user_email,
                                        'group_name': '',
                                        'timestamp': int(datetime.now().timestamp())
                                    })
                                    print(f"✅ Created tracking record: {tracking_id}")
                            
                            msg = f"✅ Your {automation_type.replace('_', ' ').lower()} request is being processed. IT will review and approve shortly.\n\nWhile IT reviews this, I can still help you with other needs. Just ask!"
                            send_slack_message(channel, msg)
                            
                            # Log to conversation history
                            if conv_data.get('interaction_id'):
                                update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                        else:
                            msg = "❌ Error processing your request. Please try again or contact IT directly."
                            if conv_data.get('interaction_id'):
                                update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                                send_error_recovery_message(channel, msg, conv_data['interaction_id'], conv_data['timestamp'], user_id)
                            else:
                                send_slack_message(channel, msg)
                        
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
                    
                    # Check for distribution list requests
                    elif any(word in message_lower for word in ['add me to', 'distribution list', 'distro list', 'email group']):
                        print(f"Distribution list request detected: {message}")
                        real_name, user_email = get_user_info_from_slack(user_id)
                        distribution_list = extract_distribution_list_name(message)
                        
                        # Search Exchange for matching DLs with progress indicator
                        import threading
                        search_complete = threading.Event()
                        
                        def send_progress_message():
                            if not search_complete.wait(5):
                                msg = "🔍 Still working on it..."
                                send_slack_message(channel, msg)
                                conv_data = user_interaction_ids.get(user_id, {})
                                if conv_data.get('interaction_id'):
                                    update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                        
                        progress_thread = threading.Thread(target=send_progress_message)
                        progress_thread.start()
                        
                        matches = query_group_type(distribution_list)
                        search_complete.set()
                        
                        if not matches:
                            send_slack_message(channel, f"❌ No distribution lists found matching '{distribution_list}'")
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        # Filter to only show DLs
                        dl_matches = [m for m in matches if m['type'] == 'DISTRIBUTION_LIST']
                        
                        if not dl_matches:
                            send_slack_message(channel, f"❌ No distribution lists found matching '{distribution_list}'. Found SSO groups instead - try 'add me to {distribution_list} sso group'")
                            return {'statusCode': 200, 'body': 'OK'}
                        
                        if len(dl_matches) > 1:
                            # Multiple matches - ask user to select
                            group_list = "\n".join([f"• {g['name']}" for g in dl_matches])
                            msg = f"🔍 Found multiple distribution lists matching '{distribution_list}':\n\n{group_list}\n\nPlease reply with the exact list name you want."
                            send_slack_message(channel, msg)
                            
                            # Log to conversation history
                            conv_data = user_interaction_ids.get(user_id, {})
                            if conv_data.get('interaction_id'):
                                update_conversation(conv_data['interaction_id'], conv_data['timestamp'], msg, from_bot=True)
                            
                            # Schedule engagement prompts for this conversation
                            conv_data = user_interaction_ids.get(user_id, {})
                            if conv_data.get('interaction_id'):
                                schedule_auto_resolve(conv_data['interaction_id'], conv_data['timestamp'], user_id)
                            
                            # Store pending selection
                            table = dynamodb.Table('it-actions')
                            table.put_item(Item={
                                'action_id': f"pending_selection_{user_email}_{int(datetime.now().timestamp())}",
                                'requester': user_email,
                                'status': 'PENDING_SELECTION',
                                'timestamp': int(datetime.now().timestamp()),
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
                        
                        # Mark conversation as awaiting approval
                        if conv_data.get('interaction_id'):
                            mark_conversation_awaiting_approval(conv_data['interaction_id'], conv_data['timestamp'])
                        
                        response = f"""📧 **Distribution List Request Received**

**Requested List:** `{exact_dl}`
**Status:** Pending IT approval

I've sent your request to the IT team for approval. You'll be notified once they review it!"""
                        
                        send_slack_message(channel, response)
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
            user_id = event['user_id']
            prompt_number = event.get('prompt_number', 1)
            
            # Check if conversation is still in progress
            response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
            if 'Item' in response:
                item = response['Item']
                # Skip if awaiting approval or already closed
                if item.get('awaiting_approval') or item.get('outcome') != 'In Progress':
                    print(f"⏭️ Skipping engagement prompt for {interaction_id} - not in progress")
                    return {'statusCode': 200, 'body': 'OK'}
                
                # Get user's channel
                user_info = interactions_table.scan(
                    FilterExpression='user_id = :uid',
                    ExpressionAttributeValues={':uid': user_id},
                    Limit=1
                )
                
                # Send engagement prompt with buttons
                if prompt_number == 1:
                    message = f"👋 Are you still there? Do you still need help with {item.get('description', 'your request')}?"
                else:
                    message = f"👋 Just checking in - are you still working on {item.get('description', 'your request')}?"
                
                # Get channel from DynamoDB or use direct message
                channel = f"@{user_id}"
                
                blocks = [
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
                                "text": {"type": "plain_text", "text": "✅ Yes, still working on it", "emoji": True},
                                "action_id": f"engagement_yes_{interaction_id}_{timestamp}",
                                "style": "primary"
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "🎫 Create Ticket", "emoji": True},
                                "action_id": f"engagement_ticket_{interaction_id}_{timestamp}"
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "✅ No, I'm all set", "emoji": True},
                                "action_id": f"engagement_resolved_{interaction_id}_{timestamp}",
                                "style": "primary"
                            }
                        ]
                    }
                ]
                
                send_slack_message(channel, message, blocks=blocks)
                
                # Log to conversation history
                update_conversation(interaction_id, timestamp, message, from_bot=True)
                
                print(f"✅ Sent engagement prompt #{prompt_number} for {interaction_id}")
            
            return {'statusCode': 200, 'body': 'OK'}
        
        # Handle auto-resolve after timeout
        elif event.get('auto_resolve'):
            interaction_id = event['interaction_id']
            timestamp = event['timestamp']
            user_id = event['user_id']
            
            # Check if still in progress (not already resolved by user)
            response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
            if 'Item' in response:
                item = response['Item']
                # Skip if awaiting approval - those have their own 5-day timeout
                if item.get('awaiting_approval'):
                    print(f"⏭️ Skipping auto-resolve for {interaction_id} - awaiting approval")
                    return {'statusCode': 200, 'body': 'OK'}
                
                if item.get('outcome') == 'In Progress':
                    # Send Slack notification
                    channel = f"@{user_id}"
                    message = f"⏱️ I haven't heard back from you, so I'm closing this conversation about *{item.get('description', 'your request')}*. Feel free to message me again if you still need help!"
                    send_slack_message(channel, message)
                    
                    # Auto-resolve as timed out
                    update_conversation(interaction_id, timestamp, "Auto-resolved (no response after 15 minutes)", from_bot=True, outcome='Timed Out - No Response')
                    print(f"✅ Auto-resolved {interaction_id}")
            
            return {'statusCode': 200, 'body': 'OK'}
        
        # Handle approval timeout check (triggered daily by EventBridge)
        elif event.get('check_approval_timeouts'):
            print("🔍 Checking for timed-out approval requests...")
            
            # Scan for conversations awaiting approval older than 5 days
            five_days_ago = int((datetime.utcnow() - timedelta(days=5)).timestamp())
            
            response = interactions_table.scan(
                FilterExpression='awaiting_approval = :true AND #ts < :timeout',
                ExpressionAttributeNames={'#ts': 'timestamp'},
                ExpressionAttributeValues={':true': True, ':timeout': five_days_ago}
            )
            
            timed_out_approvals = response.get('Items', [])
            print(f"Found {len(timed_out_approvals)} timed-out approval requests")
            
            for item in timed_out_approvals:
                interaction_id = item['interaction_id']
                timestamp = item['timestamp']
                user_id = item['user_id']
                user_name = item.get('user_name', 'Unknown User')
                description = item.get('description', 'approval request')
                
                # Get user email
                real_name, user_email = get_user_info_from_slack(user_id)
                
                # Create ticket for timed-out approval
                if save_ticket_to_dynamodb(user_id, user_name, user_email, interaction_id, timestamp):
                    print(f"✅ Created ticket for timed-out approval: {interaction_id}")
                    
                    # Update conversation outcome
                    update_conversation(interaction_id, timestamp, 
                                      "Approval timed out after 5 days - ticket created", 
                                      from_bot=True, outcome='Escalated to Ticket')
                    
                    # Notify user
                    channel = f"@{user_id}"
                    message = f"⏱️ Your approval request for *{description}* has been pending for 5 days. I've created a ticket and escalated it to IT Support. They'll follow up with you directly."
                    send_slack_message(channel, message)
                else:
                    print(f"❌ Failed to create ticket for: {interaction_id}")
            
            return {'statusCode': 200, 'body': f'Processed {len(timed_out_approvals)} timed-out approvals'}
        
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
            
            # Upload Confluence images if relevant
            try:
                auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
                auth_b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
                search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/search?cql=label=foritchatbot&limit=5"
                req = urllib.request.Request(search_url)
                req.add_header('Authorization', f'Basic {auth_b64}')
                req.add_header('Accept', 'application/json')
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    for page in data.get('results', [])[:2]:
                        images = get_confluence_images(page['id'])
                        for img in images:
                            try:
                                req = urllib.request.Request(img['download_url'])
                                req.add_header('Authorization', f'Basic {auth_b64}')
                                with urllib.request.urlopen(req, timeout=5) as img_response:
                                    if img_response.status == 200:
                                        img_data = base64.b64encode(img_response.read()).decode('utf-8')
                                        upload_to_slack(channel, img_data, img['title'])
                            except:
                                pass
            except:
                pass
            
            # Update conversation with bot response
            if interaction_id and timestamp:
                update_conversation(interaction_id, timestamp, claude_response, from_bot=True)
            
            # Track the bot's response in conversation history
            if image_analysis:
                full_response = f"{claude_response}\n\n[Image Analysis: {image_analysis}]"
                track_user_message(user_id, full_response, is_bot_response=True)
            else:
                track_user_message(user_id, claude_response, is_bot_response=True)
            
            print(f"Sent Claude response to Slack")
            
            # Send follow-up prompt with buttons after 3 seconds
            time.sleep(3)
            
            if interaction_id and timestamp:
                send_resolution_prompt(channel, user_id, interaction_id, timestamp)
        
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 200, 'body': 'OK'}
