import os
import boto3
import json
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Initialize Slack app
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

SYSTEM_PROMPT = """You are an IT helpdesk assistant. Always attempt troubleshooting first before escalating.

For common issues, provide step-by-step solutions:
- Slow computer: Check running processes, restart, clear cache, check disk space
- Password resets: Guide through self-service options first
- Software issues: Try restart, reinstall, check compatibility
- Network problems: Check cables, restart router, verify settings
- Email issues: Check settings, clear cache, verify credentials

Only escalate to human IT support if:
1. The issue involves hardware replacement
2. Security breaches or suspicious activity
3. After trying 2-3 troubleshooting steps without success
4. User explicitly requests human assistance

Always be helpful and provide specific actionable steps."""

def get_bedrock_response(message):
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ],
        "max_tokens": 300,
        "temperature": 0.3
    }
    
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=json.dumps(body)
    )
    
    result = json.loads(response['body'].read())
    return result['content'][0]['text']

@app.message("help")
def handle_help(message, say):
    say("Hi! I'm your IT helpdesk assistant. Ask me about:\n• Password issues\n• Software problems\n• Hardware troubleshooting\n• Network connectivity\n• Email/calendar issues")

@app.event("app_mention")
def handle_mention(event, say):
    user_message = event['text'].split('>', 1)[1].strip() if '>' in event['text'] else event['text']
    
    try:
        response = get_bedrock_response(user_message)
        say(f"🤖 {response}")
    except Exception as e:
        print(f"Error: {e}")
        say(f"I encountered an error: {str(e)}. Let me try to help anyway - what specific IT issue are you having?")

@app.message("")
def handle_dm(message, say):
    if message['channel_type'] == 'im':
        try:
            response = get_bedrock_response(message['text'])
            say(f"🤖 {response}")
        except Exception as e:
            print(f"Error: {e}")
            say(f"I encountered an error: {str(e)}. Let me try to help anyway - what specific IT issue are you having?")

if __name__ == "__main__":
    print("🚀 Starting Slack bot...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("✅ Bot is running and listening for messages!")
    print("Press Ctrl+C to stop the bot")
    handler.start()
