import re

# Read the file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_selection_fixed.py', 'r') as f:
    content = f.read()

# Find and replace the button message with simple text
old_button_message = '''                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": ":speech_balloon: *Did that help resolve your issue?*"
                                }
                            },
                            {
                                "type": "actions",
                                "elements": [
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": "Yes, resolved"},
                                        "style": "primary",
                                        "action_id": f"resolved_{interaction_id}_{timestamp}"
                                    },
                                    {
                                        "type": "button", 
                                        "text": {"type": "plain_text", "text": "No, still need help"},
                                        "action_id": f"unresolved_{interaction_id}_{timestamp}"
                                    },
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": "Create ticket"},
                                        "action_id": f"ticket_{interaction_id}_{timestamp}"
                                    }
                                ]'''

new_simple_message = '''                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": ":speech_balloon: *Did that help resolve your issue?*\\n\\nReply with:\\n• \\"yes\\" if resolved\\n• \\"no\\" if you still need help\\n• \\"create ticket\\" to submit a support request"
                                }'''

content = content.replace(old_button_message, new_simple_message)

# Write the fixed file
with open('/Users/matt/Brie-IT-Agent/lambda_it_bot_confluence_no_buttons.py', 'w') as f:
    f.write(content)

print("Buttons removed, text responses added!")
