import re

# Read the file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_with_sop_final.py', 'r') as f:
    content = f.read()

# Fix the SOP pattern functions
old_sop_dl = '''def is_exact_sop_dl_request(message):
    """Only exact SOP DL patterns"""
    sop_patterns = [
        'add me to the employees dl',
        'add me to employees dl',
        'add me to the employees distribution list',
        'add me to employees distribution list'
    ]
    return message.strip().lower() in sop_patterns'''

new_sop_dl = '''def is_exact_sop_dl_request(message):
    """Only exact SOP DL patterns"""
    print(f"DEBUG: Checking DL pattern for: '{message}'")
    sop_patterns = [
        'add me to the employees dl',
        'add me to employees dl',
        'add me to the employees distribution list',
        'add me to employees distribution list'
    ]
    normalized = message.strip().lower()
    result = normalized in sop_patterns
    print(f"DEBUG: DL pattern match result: {result}")
    return result'''

old_sop_sso = '''def is_exact_sso_request(message):
    """Only exact SSO request patterns"""
    exact_patterns = [
        'add me to clickup sso group',
        'add me to clickup',
        'give me access to clickup'
    ]
    return message.strip().lower() in exact_patterns'''

new_sop_sso = '''def is_exact_sso_request(message):
    """Only exact SSO request patterns"""
    print(f"DEBUG: Checking SSO pattern for: '{message}'")
    exact_patterns = [
        'add me to clickup sso group',
        'add me to clickup',
        'give me access to clickup'
    ]
    normalized = message.strip().lower()
    result = normalized in exact_patterns
    print(f"DEBUG: SSO pattern match result: {result}")
    return result'''

# Replace the functions
content = content.replace(old_sop_dl, new_sop_dl)
content = content.replace(old_sop_sso, new_sop_sso)

# Add debug logging to lambda_handler
old_handler_check = '''                # Check SOP patterns first
                if handle_user_selection(message, user_id, channel):
                    return {'statusCode': 200, 'body': 'Selection processed'}
                
                if is_exact_sop_dl_request(message):
                    return handle_sop_dl_request(message, user_id, channel)
                elif is_exact_sso_request(message):
                    return handle_sop_sso_request(message, user_id, channel)'''

new_handler_check = '''                # Check SOP patterns first
                print(f"DEBUG: Processing message: '{message}' from user: {user_id}")
                
                if handle_user_selection(message, user_id, channel):
                    print("DEBUG: User selection handled")
                    return {'statusCode': 200, 'body': 'Selection processed'}
                
                if is_exact_sop_dl_request(message):
                    print("DEBUG: SOP DL request detected")
                    return handle_sop_dl_request(message, user_id, channel)
                elif is_exact_sso_request(message):
                    print("DEBUG: SOP SSO request detected")
                    return handle_sop_sso_request(message, user_id, channel)
                
                print("DEBUG: No SOP pattern matched, continuing to comprehensive system")'''

content = content.replace(old_handler_check, new_handler_check)

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_with_sop_fixed.py', 'w') as f:
    f.write(content)

print("SOP patterns fixed with debug logging!")
