import re

# Read the file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_with_sop_fixed.py', 'r') as f:
    content = f.read()

# Find the SOP check section and add early returns
old_sop_section = '''                if handle_user_selection(message, user_id, channel):
                    print("DEBUG: User selection handled")
                    return {'statusCode': 200, 'body': 'Selection processed'}
                
                if is_exact_sop_dl_request(message):
                    print("DEBUG: SOP DL request detected")
                    return handle_sop_dl_request(message, user_id, channel)
                elif is_exact_sso_request(message):
                    print("DEBUG: SOP SSO request detected")
                    return handle_sop_sso_request(message, user_id, channel)
                
                print("DEBUG: No SOP pattern matched, continuing to comprehensive system")'''

new_sop_section = '''                if handle_user_selection(message, user_id, channel):
                    print("DEBUG: User selection handled - EARLY RETURN")
                    return {'statusCode': 200, 'body': 'Selection processed'}
                
                if is_exact_sop_dl_request(message):
                    print("DEBUG: SOP DL request detected - EARLY RETURN")
                    return handle_sop_dl_request(message, user_id, channel)
                elif is_exact_sso_request(message):
                    print("DEBUG: SOP SSO request detected - EARLY RETURN")  
                    return handle_sop_sso_request(message, user_id, channel)
                
                print("DEBUG: No SOP pattern matched, continuing to comprehensive system")'''

content = content.replace(old_sop_section, new_sop_section)

# Also need to prevent the comprehensive system from processing these patterns
# Find where the comprehensive system processes messages and add exclusions

# Look for the main message processing in comprehensive system
# This is likely where it detects SSO and DL requests

# Add exclusion check right after the SOP section
sop_end_marker = 'print("DEBUG: No SOP pattern matched, continuing to comprehensive system")'
insertion_point = content.find(sop_end_marker) + len(sop_end_marker)

exclusion_check = '''
                
                # Skip comprehensive processing if this was an SOP pattern that didn't match exactly
                # This prevents duplicate processing
                if any(pattern in message for pattern in ['add me to clickup', 'add me to employees', 'add me to the employees']):
                    print("DEBUG: Potential SOP pattern detected but not exact match - skipping comprehensive processing")
                    return {'statusCode': 200, 'body': 'Message processed'}'''

# Insert the exclusion check
content = content[:insertion_point] + exclusion_check + content[insertion_point:]

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_no_duplicates.py', 'w') as f:
    f.write(content)

print("Duplicate processing fixed!")
