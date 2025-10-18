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
import re
import urllib3

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

def lambda_handler(event, context):
    """Main handler with SOP integration"""
    print(f"Received event: {json.dumps(event)}")
    
    try:
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
            
            # SOP deduplication
            if is_duplicate_message(user_id, channel, ts, message):
                return {'statusCode': 200, 'body': 'Duplicate message ignored'}
            
        else:
            message = event.get('message', '').lower()
            user_id = event.get('user_id')
            channel = event.get('channel')
        
        # SOP workflow checks first
        if handle_user_selection(message, user_id, channel):
            return {'statusCode': 200, 'body': 'Selection processed'}
        
        if is_exact_sop_dl_request(message):
            return handle_sop_dl_request(message, user_id, channel)
        elif is_exact_sso_request(message):
            return handle_sop_sso_request(message, user_id, channel)
        else:
            # Route to original comprehensive system
            return handle_original_comprehensive(event, context)
            
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {'statusCode': 500, 'body': 'Internal server error'}

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
        send_slack_message(channel, "🔍 Checking your request...")
    
    send_sop_list(channel)
    return {'statusCode': 200, 'body': 'SOP list sent'}

def handle_sop_sso_request(message, user_id, channel):
    """Handle SSO requests with SOP approval workflow"""
    if channel:
        send_slack_message(channel, "🔍 Checking your request...")
    
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
        send_slack_message(channel, "✅ Your SSO request is being processed. IT will review and approve shortly.")
    
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
    
    message = "**Employee Distribution Lists**\n\nPlease select from:\n\n"
    for option in sop_options:
        message += f"• {option}\n"
    message += "\nPlease reply with the exact group name you want."
    
    send_slack_message(channel, message)

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

def is_duplicate_message(user_id, channel, ts, message):
    """Check if message is duplicate using DynamoDB"""
    try:
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

def handle_original_comprehensive(event, context):
    """Handle with original comprehensive system - simplified version"""
    try:
        # Extract message details
        if 'body' in event:
            body = json.loads(event['body'])
            slack_event = body.get('event', {})
            message_text = slack_event.get('text', '')
            user_id = slack_event.get('user')
            channel = slack_event.get('channel')
        else:
            message_text = event.get('message', '')
            user_id = event.get('user_id')
            channel = event.get('channel')
        
        # Simple performance response for now
        if any(keyword in message_text.lower() for keyword in ['slow', 'performance', 'workspace', 'laptop']):
            response = """🔧 **Performance Troubleshooting:**

1. Check Task Manager for high CPU processes
2. Restart your computer  
3. Check available disk space
4. Clear browser cache

💡 For WorkSpaces: say "check my workspace"
💡 Need help? Say "create ticket" """
            
            send_slack_message(channel, response)
            return {'statusCode': 200, 'body': 'Performance help sent'}
        
        # Default response
        response = "👋 I'm here to help with IT support! What can I help you with?"
        send_slack_message(channel, response)
        return {'statusCode': 200, 'body': 'General help sent'}
        
    except Exception as e:
        print(f"Error in comprehensive handler: {e}")
        return {'statusCode': 500, 'body': 'Error processing request'}
