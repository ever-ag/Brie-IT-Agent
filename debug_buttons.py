import re

# Read the file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_buttons_fixed.py', 'r') as f:
    content = f.read()

# Add debug logging right at the start of lambda_handler
old_start = '''def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"Received event: {json.dumps(event)}")'''

new_start = '''def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"Received event: {json.dumps(event)}")
    
    # DEBUG: Check event type
    if 'body' in event:
        body = json.loads(event['body'])
        event_type = body.get('type')
        print(f"DEBUG: Event type detected: {event_type}")
        
        if event_type == 'interactive':
            print("DEBUG: BUTTON CLICK DETECTED!")
            print(f"DEBUG: Full interactive payload: {json.dumps(body)}")'''

content = content.replace(old_start, new_start)

# Write the debug version
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_debug_buttons.py', 'w') as f:
    f.write(content)

print("Button debug logging added!")
