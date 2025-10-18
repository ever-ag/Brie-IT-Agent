import re

# Read the original file with buttons
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_selection_fixed.py', 'r') as f:
    content = f.read()

# Find the lambda_handler and add proper interactive handling at the very beginning
old_handler_start = '''def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"Received event: {json.dumps(event)}")
    
    # DEBUG: Check event type
    if 'body' in event:
        body = json.loads(event['body'])
        event_type = body.get('type')
        print(f"DEBUG: Event type detected: {event_type}")
        
        if event_type == 'interactive':
            print("DEBUG: BUTTON CLICK DETECTED!")
            print(f"DEBUG: Full interactive payload: {json.dumps(body)}")
    
    try:

        # Handle interactive components (button clicks) FIRST
        if 'body' in event:
            body = json.loads(event['body'])
            if body.get('type') == 'url_verification':
                return {'statusCode': 200, 'body': body['challenge']}
            
            # Handle button clicks before SOP checks
            if body.get('type') == 'interactive':
                print("DEBUG: Interactive button click detected - processing with comprehensive system")
                # Let comprehensive system handle all button interactions
                pass  # Continue to comprehensive system'''

new_handler_start = '''def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Handle interactive components (button clicks) FIRST - before any other processing
        if 'body' in event:
            body = json.loads(event['body'])
            
            # URL verification
            if body.get('type') == 'url_verification':
                return {'statusCode': 200, 'body': body['challenge']}
            
            # Handle interactive events (button clicks) immediately
            if body.get('type') == 'interactive':
                print("DEBUG: INTERACTIVE BUTTON CLICK DETECTED!")
                
                # Parse the payload - it might be URL encoded
                payload = body.get('payload')
                if isinstance(payload, str):
                    import urllib.parse
                    payload = json.loads(urllib.parse.unquote(payload))
                else:
                    payload = body
                
                print(f"DEBUG: Parsed payload: {json.dumps(payload)}")
                
                # Extract action info
                actions = payload.get('actions', [])
                if actions:
                    action_id = actions[0].get('action_id', '')
                    user_id = payload.get('user', {}).get('id', '')
                    channel = payload.get('channel', {}).get('id', '')
                    
                    print(f"DEBUG: Button action_id: {action_id}, user: {user_id}, channel: {channel}")
                    
                    # Handle resolution buttons
                    if action_id.startswith('resolved_'):
                        print("DEBUG: Resolved button clicked")
                        handle_resolution_button(action_id, user_id, channel)
                        return {'statusCode': 200, 'body': 'Button handled'}
                    elif action_id.startswith('unresolved_'):
                        print("DEBUG: Unresolved button clicked") 
                        handle_resolution_button(action_id, user_id, channel)
                        return {'statusCode': 200, 'body': 'Button handled'}
                    elif action_id.startswith('ticket_'):
                        print("DEBUG: Ticket button clicked")
                        handle_resolution_button(action_id, user_id, channel)
                        return {'statusCode': 200, 'body': 'Button handled'}
                
                return {'statusCode': 200, 'body': 'Interactive event processed'}'''

content = content.replace(old_handler_start, new_handler_start)

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_buttons_working.py', 'w') as f:
    f.write(content)

print("Interactive button handling fixed!")
