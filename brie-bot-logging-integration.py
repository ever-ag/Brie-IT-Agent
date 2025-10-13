"""
Add this code to your Slack bot Lambda functions to log interactions
"""

import boto3
import json
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

def log_bot_interaction(user_name, message_text, action_taken, ticket_created=False, metadata=None):
    """
    Log a Slack bot interaction
    
    Usage examples:
    
    # When user gets wiki solution
    log_bot_interaction(
        user_name="Scott Johnson",
        message_text="My Excel keeps crashing on Mac",
        action_taken="Sent wiki article: Excel Mac Performance",
        metadata={"wiki_article_id": "123456"}
    )
    
    # When DL request is automated
    log_bot_interaction(
        user_name="Bob Smith",
        message_text="Can you add me to DL-Sales?",
        action_taken="Automated DL request approved",
        metadata={"dl_name": "DL-Sales", "approved_by": "auto"}
    )
    
    # When ticket is created
    log_bot_interaction(
        user_name="Matt Denecke",
        message_text="Printer not working",
        action_taken="Created ticket after troubleshooting",
        ticket_created=True,
        metadata={"ticket_id": "CorpIT-28905"}
    )
    """
    try:
        # Auto-categorize interaction type
        interaction_type = categorize_interaction(message_text, action_taken)
        
        # Determine outcome
        if ticket_created:
            outcome = "Ticket Created"
        elif 'automated' in action_taken.lower() or 'approved' in action_taken.lower():
            outcome = "Resolved by Brie"
        elif 'wiki' in action_taken.lower() or 'article' in action_taken.lower():
            outcome = "Self-Service Solution"
        else:
            outcome = "In Progress"
        
        # Create interaction record
        interaction_id = str(uuid.uuid4())
        timestamp = int(datetime.utcnow().timestamp())
        
        item = {
            'interaction_id': interaction_id,
            'timestamp': timestamp,
            'user_name': user_name,
            'interaction_type': interaction_type,
            'description': message_text[:200],  # Truncate to 200 chars
            'outcome': outcome,
            'date': datetime.utcnow().isoformat(),
            'metadata': json.dumps(metadata) if metadata else '{}'
        }
        
        interactions_table.put_item(Item=item)
        print(f"✅ Logged interaction: {user_name} - {interaction_type} - {outcome}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to log interaction: {e}")
        return False

def categorize_interaction(message_text, action_taken):
    """Auto-categorize the interaction type"""
    text = f"{message_text} {action_taken}".lower()
    
    if any(kw in text for kw in ['distribution list', 'dl ', 'shared mailbox', 'sso', 'access to', 'add me to']):
        return "Access Management"
    
    if any(kw in text for kw in ['excel', 'word', 'outlook', 'powerpoint', 'teams', 'slack', 'chrome', 'browser', 'software']):
        return "Application Support"
    
    if any(kw in text for kw in ['printer', 'monitor', 'keyboard', 'mouse', 'laptop', 'desktop', 'hardware']):
        return "Hardware Support"
    
    if any(kw in text for kw in ['wifi', 'vpn', 'network', 'internet', 'connection', 'slow', 'disconnect', 'workspace']):
        return "Network & Connectivity"
    
    if any(kw in text for kw in ['password', 'login', 'account', 'authentication', 'mfa', '2fa', 'locked out']):
        return "Account & Authentication"
    
    if 'wiki' in text or 'knowledge' in text or 'article' in text:
        return "Knowledge Base"
    
    return "General Support"


# Example integration points in your Slack bot:

# 1. After sending wiki solution
# log_bot_interaction(
#     user_name=user_name,
#     message_text=user_message,
#     action_taken=f"Sent wiki article: {wiki_title}",
#     metadata={"wiki_url": wiki_url, "article_id": article_id}
# )

# 2. After DL/SSO automation
# log_bot_interaction(
#     user_name=user_name,
#     message_text=user_message,
#     action_taken=f"Automated {request_type} request",
#     metadata={"request_type": request_type, "resource": resource_name}
# )

# 3. After creating ticket
# log_bot_interaction(
#     user_name=user_name,
#     message_text=user_message,
#     action_taken="Created support ticket",
#     ticket_created=True,
#     metadata={"ticket_id": ticket_id}
# )
