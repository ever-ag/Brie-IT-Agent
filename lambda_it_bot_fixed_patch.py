# Patch for lambda_it_bot_fixed.py
# This shows the changes needed to pass timestamp to approval system

# CHANGE 1: Update trigger_automation_workflow signature (line 1836)
def trigger_automation_workflow(user_email, user_name, message, channel, thread_ts, automation_type, user_id=None, interaction_id=None, timestamp=None):
    """Trigger full automation workflow with AI processing"""
    try:
        import re
        lambda_client = boto3.client('lambda')
        
        # Clean message - handle Slack link formatting properly
        clean_message = re.sub(r'<mailto:([^|>]+)\|[^>]+>', r'\1', message)
        clean_message = re.sub(r'<[^|>]+\|([^>]+)>', r'\1', clean_message)
        clean_message = re.sub(r'<([^|>]+)>', r'\1', clean_message)
        
        # Create email data for action processor
        email_data = {
            "sender": user_email,
            "subject": f"SSO Request from {user_name}",
            "body": clean_message,
            "messageId": f"slack_{channel}_{thread_ts}",
            "source": "it-helpdesk-bot",
            "slackContext": {
                "channel": channel,
                "thread_ts": thread_ts,
                "user_name": user_name,
                "user_id": user_id,
                "timestamp": timestamp  # ADD THIS LINE
            },
            "interaction_id": interaction_id
        }
        # ... rest of function

# CHANGE 2: Update the call to trigger_automation_workflow (line 3860)
execution_arn = trigger_automation_workflow(
    user_email, 
    real_name, 
    message, 
    channel, 
    slack_event.get('ts', ''),
    automation_type,
    user_id,
    interaction_id,  # Pass conversation ID
    timestamp  # ADD THIS LINE
)
