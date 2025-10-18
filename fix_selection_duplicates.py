import re

# Read the file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_debug_buttons.py', 'r') as f:
    content = f.read()

# Find the handle_user_selection function and add deduplication
old_selection = '''def handle_user_selection(message, user_id, channel):
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
            send_sop_slack_message(channel, "🔄 Still working on it...")
        
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
    
    return False'''

new_selection = '''def handle_user_selection(message, user_id, channel):
    """Handle user selection from SOP list with deduplication"""
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
        # Deduplication check for user selections
        try:
            dynamodb_resource = boto3.resource('dynamodb')
            table = dynamodb_resource.Table('it-actions')
            
            selection_key = f"selection_{user_id}_{selected_group}_{int(datetime.now().timestamp() // 10)}"  # 10-second window
            
            table.put_item(
                Item={
                    'action_id': selection_key,
                    'message': message_clean,
                    'timestamp': int(datetime.now().timestamp()),
                    'ttl': int(datetime.now().timestamp()) + 60  # 1 minute TTL
                },
                ConditionExpression='attribute_not_exists(action_id)'
            )
            
        except dynamodb_resource.meta.client.exceptions.ConditionalCheckFailedException:
            print(f"DEBUG: Duplicate selection ignored for {selected_group}")
            return True  # Return True to prevent further processing
        except Exception as e:
            print(f"Selection dedup error: {e}")
        
        if channel:
            send_sop_slack_message(channel, "🔄 Still working on it...")
        
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
    
    return False'''

content = content.replace(old_selection, new_selection)

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_selection_fixed.py', 'w') as f:
    f.write(content)

print("Selection duplicates fixed!")
