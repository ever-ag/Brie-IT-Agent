import re

# Read the file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_no_duplicates.py', 'r') as f:
    content = f.read()

# Find the SOP section and move interactive handling before it
old_sop_start = '''        # SOP workflow checks first
        if 'body' in event:
            body = json.loads(event['body'])
            if body.get('type') == 'url_verification':
                return {'statusCode': 200, 'body': body['challenge']}
            
            slack_event = body.get('event', {})
            if slack_event.get('type') == 'message' and 'bot_id' not in slack_event:'''

new_sop_start = '''        # Handle interactive components (button clicks) FIRST
        if 'body' in event:
            body = json.loads(event['body'])
            if body.get('type') == 'url_verification':
                return {'statusCode': 200, 'body': body['challenge']}
            
            # Handle button clicks before SOP checks
            if body.get('type') == 'interactive':
                print("DEBUG: Interactive button click detected - processing with comprehensive system")
                # Let comprehensive system handle all button interactions
                pass  # Continue to comprehensive system
            
            # SOP workflow checks for messages only
            slack_event = body.get('event', {})
            if slack_event.get('type') == 'message' and 'bot_id' not in slack_event:'''

content = content.replace(old_sop_start, new_sop_start)

# Also need to ensure interactive events skip SOP processing entirely
# Add check right after the SOP section
old_continue = '''                print("DEBUG: No SOP pattern matched, continuing to comprehensive system")
                
                # Skip comprehensive processing if this was an SOP pattern that didn't match exactly
                # This prevents duplicate processing
                if any(pattern in message for pattern in ['add me to clickup', 'add me to employees', 'add me to the employees']):
                    print("DEBUG: Potential SOP pattern detected but not exact match - skipping comprehensive processing")
                    return {'statusCode': 200, 'body': 'Message processed'}'''

new_continue = '''                print("DEBUG: No SOP pattern matched, continuing to comprehensive system")
                
                # Skip comprehensive processing if this was an SOP pattern that didn't match exactly
                # This prevents duplicate processing
                if any(pattern in message for pattern in ['add me to clickup', 'add me to employees', 'add me to the employees']):
                    print("DEBUG: Potential SOP pattern detected but not exact match - skipping comprehensive processing")
                    return {'statusCode': 200, 'body': 'Message processed'}
            
            # For interactive events (button clicks), always go to comprehensive system
            elif body.get('type') == 'interactive':
                print("DEBUG: Interactive event - routing to comprehensive system")
                # Continue to comprehensive system for button handling'''

content = content.replace(old_continue, new_continue)

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_buttons_fixed.py', 'w') as f:
    f.write(content)

print("Button handling fixed!")
