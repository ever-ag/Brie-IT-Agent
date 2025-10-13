import boto3
import json
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

# IT Helpdesk system prompt
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

def chat_with_bedrock(user_message, conversation_history=[]):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})
    
    body = {
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.3
    }
    
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=json.dumps(body)
    )
    
    result = json.loads(response['body'].read())
    return result['content'][0]['text']

@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head><title>IT Helpdesk Chat</title></head>
    <body>
        <h1>IT Helpdesk Assistant</h1>
        <div id="chat" style="height:400px;overflow-y:scroll;border:1px solid #ccc;padding:10px;"></div>
        <input type="text" id="message" placeholder="Type your IT question..." style="width:80%;">
        <button onclick="sendMessage()">Send</button>
        
        <script>
        function sendMessage() {
            const message = document.getElementById('message').value;
            if (!message) return;
            
            document.getElementById('chat').innerHTML += '<p><b>You:</b> ' + message + '</p>';
            document.getElementById('message').value = '';
            
            fetch('/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: message})
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('chat').innerHTML += '<p><b>IT Assistant:</b> ' + data.response + '</p>';
                document.getElementById('chat').scrollTop = document.getElementById('chat').scrollHeight;
            });
        }
        
        document.getElementById('message').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
        </script>
    </body>
    </html>
    ''')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    response = chat_with_bedrock(user_message)
    return jsonify({'response': response})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5002)
