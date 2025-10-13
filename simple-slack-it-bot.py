import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

def get_it_response(message):
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['slow', 'sluggish', 'freeze', 'lag']):
        return """Let's troubleshoot your slow computer:

1. **Check Task Manager**: Press Ctrl+Shift+Esc (Windows) or Activity Monitor (Mac)
2. **Look for high CPU usage** - End any unnecessary processes
3. **Restart your computer** - This clears memory and temporary files
4. **Check disk space** - You need at least 15% free space
5. **Clear browser cache** - This can free up significant space

Try these steps and let me know if it's still slow!"""
    
    elif any(word in message_lower for word in ['password', 'login', 'sign in']):
        return """For password issues:

1. **Try password reset**: Go to your company's self-service portal
2. **Check caps lock** - Make sure it's off
3. **Clear browser saved passwords** - Sometimes they get corrupted
4. **Try incognito/private mode** - This bypasses cache issues

If none of these work, I can escalate to IT support."""
    
    elif any(word in message_lower for word in ['wifi', 'internet', 'network', 'connection']):
        return """Network troubleshooting steps:

1. **Check other devices** - Is WiFi working on your phone?
2. **Restart your router** - Unplug for 30 seconds, plug back in
3. **Forget and reconnect** - Remove WiFi network, reconnect with password
4. **Check network settings** - Make sure you're on the right network
5. **Try ethernet cable** - Test if wired connection works

Let me know which step helps!"""
    
    else:
        return """I can help with common IT issues:

• **Computer running slow** - Performance troubleshooting
• **Password problems** - Login and reset assistance  
• **Network issues** - WiFi and connectivity problems
• **Software crashes** - Application troubleshooting

What specific issue are you experiencing?"""

@app.message("help")
def handle_help(message, say):
    say("Hi! I'm your IT helpdesk assistant. Ask me about computer problems, passwords, network issues, or software troubles!")

@app.event("app_mention")
def handle_mention(event, say):
    user_message = event['text'].split('>', 1)[1].strip() if '>' in event['text'] else event['text']
    response = get_it_response(user_message)
    say(f"🔧 {response}")

@app.message("")
def handle_dm(message, say):
    if message['channel_type'] == 'im':
        response = get_it_response(message['text'])
        say(f"🔧 {response}")

if __name__ == "__main__":
    print("🚀 Starting Simple IT Slack bot...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("✅ Bot is running!")
    handler.start()
