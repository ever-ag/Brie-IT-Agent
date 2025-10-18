import re

# Read the approval system file
with open('/Users/matt/Brie-IT-Agent/approval_with_resolution_buttons.py', 'r') as f:
    content = f.read()

# Fix the message formatting - remove markdown and use plain text
old_messages = '''        if action_id.startswith('resolved_'):
            message = "✅ Great! Glad I could help resolve your issue. If you need anything else, just ask!"
            
        elif action_id.startswith('unresolved_'):
            message = "🔄 I understand the issue isn't resolved yet. Let me help you further.\\n\\n" + \\
                     "You can:\\n" + \\
                     "• Describe what's still not working\\n" + \\
                     "• Say 'create ticket' to submit a support request\\n" + \\
                     "• Contact IT directly: itsupport@ever.ag or 214-807-0784"
                     
        elif action_id.startswith('ticket_'):
            message = "🎫 I'll help you create a support ticket. Please describe your issue in detail and I'll submit it to the IT team."'''

new_messages = '''        if action_id.startswith('resolved_'):
            message = "Great! Glad I could help resolve your issue. If you need anything else, just ask!"
            
        elif action_id.startswith('unresolved_'):
            message = "I understand the issue isn't resolved yet. Let me help you further.\\n\\nYou can:\\n• Describe what's still not working\\n• Say 'create ticket' to submit a support request\\n• Contact IT directly: itsupport@ever.ag or 214-807-0784"
                     
        elif action_id.startswith('ticket_'):
            message = "I'll help you create a support ticket. Please describe your issue in detail and I'll submit it to the IT team."'''

content = content.replace(old_messages, new_messages)

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/approval_with_resolution_buttons_fixed.py', 'w') as f:
    f.write(content)

print("Message formatting fixed!")
