import boto3
import json
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

def log_interaction(user_name, interaction_type, description, outcome, metadata=None):
    """
    Log a user interaction with the IT Help Desk Bot
    
    Args:
        user_name: User's name (e.g., "Scott Johnson")
        interaction_type: Auto-categorized type (e.g., "Access Management", "Application Support")
        description: Brief description of the issue
        outcome: Result (e.g., "Resolved by Brie", "Escalated to IT", "Ticket Created")
        metadata: Optional dict with additional context
    """
    try:
        interaction_id = str(uuid.uuid4())
        timestamp = int(datetime.utcnow().timestamp())
        
        item = {
            'interaction_id': interaction_id,
            'timestamp': timestamp,
            'user_name': user_name,
            'interaction_type': interaction_type,
            'description': description,
            'outcome': outcome,
            'date': datetime.utcnow().isoformat(),
            'metadata': json.dumps(metadata) if metadata else '{}'
        }
        
        table.put_item(Item=item)
        print(f"✅ Logged interaction: {user_name} - {interaction_type}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to log interaction: {e}")
        return False

def categorize_interaction(message_text, action_taken):
    """
    Automatically categorize the interaction type based on message and action
    """
    text = message_text.lower()
    
    # Access Management
    if any(keyword in text for keyword in ['distribution list', 'dl ', 'shared mailbox', 'sso', 'access to', 'add me to']):
        return "Access Management"
    
    # Application Support
    if any(keyword in text for keyword in ['excel', 'word', 'outlook', 'powerpoint', 'teams', 'slack', 'chrome', 'browser']):
        return "Application Support"
    
    # Hardware Support
    if any(keyword in text for keyword in ['printer', 'monitor', 'keyboard', 'mouse', 'laptop', 'desktop', 'hardware']):
        return "Hardware Support"
    
    # Network/Connectivity
    if any(keyword in text for keyword in ['wifi', 'vpn', 'network', 'internet', 'connection', 'slow', 'disconnect']):
        return "Network & Connectivity"
    
    # Account/Authentication
    if any(keyword in text for keyword in ['password', 'login', 'account', 'authentication', 'mfa', '2fa', 'locked out']):
        return "Account & Authentication"
    
    # Knowledge Base (wiki searches)
    if 'wiki' in action_taken.lower() or 'knowledge' in action_taken.lower():
        return "Knowledge Base"
    
    # Default
    return "General Support"

def determine_outcome(action_taken, ticket_created=False):
    """
    Determine the outcome based on the action taken
    """
    if ticket_created:
        return "Ticket Created"
    elif 'automated' in action_taken.lower() or 'approved' in action_taken.lower():
        return "Resolved by Brie"
    elif 'wiki' in action_taken.lower() or 'solution' in action_taken.lower():
        return "Self-Service Solution"
    elif 'escalat' in action_taken.lower():
        return "Escalated to IT"
    else:
        return "In Progress"
