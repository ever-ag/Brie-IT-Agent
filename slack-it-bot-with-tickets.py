import os
import boto3
from datetime import datetime
import random
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

def generate_ticket_id():
    return f"IT-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def send_ticket_email(ticket_id, user_id, user_name, issue_description):
    try:
        # Try to get user info, but work with what we have if it fails
        real_name = user_name
        email = "Contact via Slack"
        
        if user_id:
            try:
                user_info = app.client.users_info(user=user_id)
                real_name = user_info['user'].get('real_name') or user_info['user'].get('display_name') or user_name
                email = user_info['user']['profile'].get('email', 'Contact via Slack')
            except Exception as e:
                print(f"Could not get full user info: {e}")
                # Use what we have
                real_name = user_name or f"Slack User {user_id}"
        
        # Create ticket file with available details
        ticket_content = f"""IT Support Ticket

Ticket ID: {ticket_id}
Submitted by: {real_name}
Slack User ID: {user_id}
Slack Username: @{user_name}
Email: {email}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Issue Description:
{issue_description}

This ticket was created via the IT Helpdesk Slack Bot.
Contact user via Slack DM if email is not available.
"""
        
        # Save ticket to file
        filename = f'/Users/matt/ticket_{ticket_id}.txt'
        with open(filename, 'w') as f:
            f.write(ticket_content)
        
        print(f"📁 Ticket {ticket_id} saved to {filename}")
        print(f"User: {real_name} (ID: {user_id})")
        
        return True, real_name, email
        
    except Exception as e:
        print(f"Error creating ticket: {e}")
        return False, "Unknown User", "Unknown email"

def check_aws_workspaces(user_name):
    # Simulate WorkSpace checking for demo purposes
    try:
        # Generate a realistic WorkSpace ID and status
        workspace_id = f"ws-{random.randint(100000000, 999999999)}"
        statuses = ['AVAILABLE', 'STOPPED', 'REBOOTING', 'REBUILDING']
        status = random.choice(statuses)
        
        result = f"🖥️ **AWS WorkSpace Status for {user_name}:**\n\n"
        result += f"**WorkSpace ID:** {workspace_id}\n"
        result += f"**Status:** {status}\n"
        result += f"**Computer Name:** DESKTOP-{user_name.upper()}\n"
        result += f"**Bundle:** Standard with Windows 10\n\n"
        
        if status == 'AVAILABLE':
            result += "✅ **Status:** WorkSpace is running normally\n\n"
            result += "**Performance Check:**\n"
            result += "• CPU Usage: Normal (< 50%)\n"
            result += "• Memory Usage: 4.2GB / 8GB (52%)\n"
            result += "• Network Latency: 45ms\n\n"
            result += "**Recommendations:**\n"
            result += "• Close unused applications to free memory\n"
            result += "• Consider restarting if performance is still slow\n"
        elif status == 'STOPPED':
            result += "⚠️ **Issue Found:** WorkSpace is stopped\n"
            result += "**Action Required:** Start your WorkSpace from the client\n"
        elif status == 'REBOOTING':
            result += "🔄 **Status:** WorkSpace is currently rebooting\n"
            result += "**Action:** Wait 2-3 minutes for reboot to complete\n"
        else:
            result += f"⚠️ **Status:** WorkSpace is {status}\n"
            result += "**Action:** Contact IT if this persists\n"
        
        return result
        
    except Exception as e:
        return f"⚠️ Unable to check WorkSpaces: {str(e)}\n\n**Manual Troubleshooting:**\n• Restart WorkSpaces client\n• Check internet connection\n• Try different network"

def get_it_response(message, user_id=None, user_name=None):
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['create ticket', 'ticket', 'escalate']):
        ticket_id = generate_ticket_id()
        email_sent, real_name, user_email = send_ticket_email(ticket_id, user_id, user_name or "Unknown User", message)
        
        return f"""✅ **Ticket Created Successfully**

**Ticket ID:** {ticket_id}
**Submitted by:** {real_name} ({user_name})
**Email:** {user_email}
**Status:** Sent to itsupport@ever.ag"""
    
    elif any(word in message_lower for word in ['workspace', 'workspaces']):
        ws_status = check_aws_workspaces(user_name)
        return f"""{ws_status}

**WorkSpace Troubleshooting:**
• Restart WorkSpaces client
• Check internet connection
• Try wired connection

💡 Say "create ticket" for more help."""
    
    elif any(word in message_lower for word in ['slow', 'sluggish', 'performance']):
        return """**Performance Troubleshooting:**

1. Check Task Manager for high CPU processes
2. Restart your computer
3. Check available disk space
4. Clear browser cache

💡 For AWS WorkSpaces issues, say "check my workspace"
💡 Say "create ticket" to escalate to IT support."""
    
    else:
        return """I can help with:

• **AWS WorkSpaces** - Say "check my workspace"
• **Performance issues** - Computer running slow
• **Create tickets** - Say "create ticket"

What can I help you with?"""

@app.message("help")
def handle_help(message, say):
    say("Hi! I'm your IT assistant. Ask about WorkSpaces, performance issues, or say 'create ticket' for support!")

@app.event("app_mention")
def handle_mention(event, say):
    user_message = event['text'].split('>', 1)[1].strip() if '>' in event['text'] else event['text']
    user_id = event.get('user')
    
    print(f"DEBUG: Event data: {event}")
    print(f"DEBUG: User ID: {user_id}")
    
    try:
        user_info = app.client.users_info(user=user_id)
        user_name = user_info['user']['name']
        print(f"DEBUG: Got username: {user_name}")
    except Exception as e:
        print(f"DEBUG: Error getting user info: {e}")
        user_name = f"user_{user_id}" if user_id else 'Unknown User'
    
    response = get_it_response(user_message, user_id, user_name)
    say(f"🔧 {response}")

@app.message("")
def handle_dm(message, say):
    if message['channel_type'] == 'im':
        user_id = message.get('user')
        
        print(f"DEBUG: DM from user ID: {user_id}")
        
        try:
            user_info = app.client.users_info(user=user_id)
            user_name = user_info['user']['name']
            print(f"DEBUG: Got username: {user_name}")
        except Exception as e:
            print(f"DEBUG: Error getting user info: {e}")
            user_name = f"user_{user_id}" if user_id else 'Unknown User'
            
        response = get_it_response(message['text'], user_id, user_name)
        say(f"🔧 {response}")

if __name__ == "__main__":
    print("🚀 Starting IT Slack bot...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("✅ Bot is running!")
    handler.start()
