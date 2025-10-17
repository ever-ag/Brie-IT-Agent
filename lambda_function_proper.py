import json
import re
import requests
import os

def detect_automation_request(message):
    sso_patterns = [
        r'add\s+(.+?)\s+to\s+(.+?)\s+sso\s+(.+?)\s+group',
        r'add\s+(.+?)\s+to\s+the\s+sso\s+(.+?)\s+group',
        r'add\s+(.+?)\s+to\s+sso\s+(.+?)\s+workspace',
        r'sso\s+(.+?)\s+workspace\s+(.+?)\s+group'
    ]
    
    for pattern in sso_patterns:
        if re.search(pattern, message.lower()):
            return True, "sso_request"
    return False, None

def send_slack_response(channel, text):
    token = os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        return False
    
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    data = {
        "channel": channel,
        "text": text
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.json().get('ok', False)
    except:
        return False

def lambda_handler(event, context):
    try:
        # Handle URL verification
        body = json.loads(event.get('body', '{}'))
        if body.get('type') == 'url_verification':
            return {
                'statusCode': 200,
                'body': body.get('challenge', '')
            }
        
        # Handle Slack events
        if body.get('type') == 'event_callback':
            slack_event = body.get('event', {})
            
            # Skip bot messages
            if slack_event.get('bot_id'):
                return {'statusCode': 200, 'body': 'OK'}
            
            text = slack_event.get('text', '').strip()
            channel = slack_event.get('channel')
            
            if not text or not channel:
                return {'statusCode': 200, 'body': 'OK'}
            
            print(f"Processing message from user_{slack_event.get('user')}: {text}")
            
            is_automation, request_type = detect_automation_request(text)
            
            if is_automation and request_type == "sso_request":
                response_text = "✅ Your SSO group request has been received and will be processed by the IT team. You'll receive an update within 24 hours."
                success = send_slack_response(channel, response_text)
                print(f"Sent response to Slack: {success}")
                return {'statusCode': 200, 'body': 'OK'}
        
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {'statusCode': 200, 'body': 'OK'}
