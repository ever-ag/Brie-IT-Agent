import boto3
import json
import uuid
from datetime import datetime, timedelta

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

CONVERSATION_TIMEOUT_MINUTES = 30

def get_or_create_conversation(user_id, user_name, message_text):
    """
    Get existing conversation or create new one
    Returns: (interaction_id, is_new_conversation)
    """
    try:
        # Check for active conversation (within timeout window)
        timeout_timestamp = int((datetime.utcnow() - timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES)).timestamp())
        
        # Scan for recent interactions by this user
        response = interactions_table.scan(
            FilterExpression='user_id = :uid AND #ts > :timeout',
            ExpressionAttributeNames={'#ts': 'timestamp'},
            ExpressionAttributeValues={
                ':uid': user_id,
                ':timeout': timeout_timestamp
            }
        )
        
        items = response.get('Items', [])
        
        # If found active conversation, return it
        if items:
            # Get most recent
            items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            active = items[0]
            
            # Check if outcome is already final (don't reopen resolved conversations)
            if active.get('outcome') not in ['Ticket Created', 'Self-Service Solution', 'Resolved by Brie']:
                print(f"✅ Found active conversation: {active['interaction_id']}")
                return active['interaction_id'], False
        
        # Create new conversation
        interaction_id = str(uuid.uuid4())
        interaction_type = categorize_interaction(message_text)
        
        item = {
            'interaction_id': interaction_id,
            'timestamp': int(datetime.utcnow().timestamp()),
            'user_id': user_id,
            'user_name': user_name,
            'interaction_type': interaction_type,
            'description': message_text[:200],
            'outcome': 'In Progress',
            'date': datetime.utcnow().isoformat(),
            'conversation_history': json.dumps([{
                'timestamp': datetime.utcnow().isoformat(),
                'message': message_text,
                'from': 'user'
            }]),
            'metadata': '{}'
        }
        
        interactions_table.put_item(Item=item)
        print(f"✅ Created new conversation: {interaction_id}")
        return interaction_id, True
        
    except Exception as e:
        print(f"❌ Error in conversation tracking: {e}")
        return None, True

def update_conversation(interaction_id, message_text, from_bot=False, outcome=None):
    """Update existing conversation with new message"""
    try:
        # Get current conversation
        response = interactions_table.get_item(
            Key={'interaction_id': interaction_id, 'timestamp': get_timestamp_for_id(interaction_id)}
        )
        
        if 'Item' not in response:
            print(f"⚠️ Conversation {interaction_id} not found")
            return False
        
        item = response['Item']
        
        # Parse conversation history
        conv_hist = item.get('conversation_history', '[]')
        history = json.loads(conv_hist) if isinstance(conv_hist, str) else conv_hist
        if not isinstance(history, list):
            history = []
        
        # Add new message
        history.append({
            'timestamp': datetime.utcnow().isoformat(),
            'message': message_text[:500],
            'from': 'bot' if from_bot else 'user'
        })
        
        # Update item
        update_expr = 'SET conversation_history = :hist, last_updated = :updated'
        expr_values = {
            ':hist': json.dumps(history),
            ':updated': datetime.utcnow().isoformat()
        }
        
        # Update outcome if provided
        if outcome:
            update_expr += ', outcome = :outcome'
            expr_values[':outcome'] = outcome
        
        interactions_table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': item['timestamp']},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values
        )
        
        print(f"✅ Updated conversation: {interaction_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error updating conversation: {e}")
        return False

def get_timestamp_for_id(interaction_id):
    """Get timestamp for interaction_id (scan to find it)"""
    try:
        response = interactions_table.scan(
            FilterExpression='interaction_id = :id',
            ExpressionAttributeValues={':id': interaction_id}
        )
        items = response.get('Items', [])
        if items:
            return items[0]['timestamp']
    except:
        pass
    return 0

def detect_resolution(message_text):
    """Detect if user indicates issue is resolved"""
    text = message_text.lower()
    
    resolved_phrases = [
        'thank', 'thanks', 'that worked', 'that fixed', 'that helped',
        'resolved', 'solved', 'fixed', 'working now', 'all set',
        'perfect', 'great', 'awesome', 'got it', 'that did it'
    ]
    
    return any(phrase in text for phrase in resolved_phrases)

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

def get_conversation_summary(interaction_id):
    """Get full conversation history for ticket creation"""
    try:
        response = interactions_table.scan(
            FilterExpression='interaction_id = :id',
            ExpressionAttributeValues={':id': interaction_id}
        )
        
        items = response.get('Items', [])
        if not items:
            return None
        
        item = items[0]
        history = json.loads(item.get('conversation_history', '[]'))
        
        # Format conversation
        summary = f"Issue: {item.get('description', 'N/A')}\n\nConversation:\n"
        for msg in history:
            from_label = "User" if msg['from'] == 'user' else "Brie"
            summary += f"\n[{msg['timestamp']}] {from_label}: {msg['message']}\n"
        
        return summary
        
    except Exception as e:
        print(f"❌ Error getting conversation summary: {e}")
        return None
