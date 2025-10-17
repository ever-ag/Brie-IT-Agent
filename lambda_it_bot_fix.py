import json
import re

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

def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        text = body.get('text', '').strip()
        
        if not text:
            return {'statusCode': 200, 'body': json.dumps({'text': 'Please provide a request.'})}
        
        is_automation, request_type = detect_automation_request(text)
        
        if is_automation and request_type == "sso_request":
            response_text = "✅ Your SSO group request has been received and will be processed by the IT team. You'll receive an update within 24 hours."
            
            return {
                'statusCode': 200,
                'body': json.dumps({'text': response_text})
            }
        
        return {
            'statusCode': 200,
            'body': json.dumps({'text': 'Request received. Please contact IT for assistance.'})
        }
        
    except Exception as e:
        return {
            'statusCode': 200,
            'body': json.dumps({'text': 'Error processing request. Please try again.'})
        }
