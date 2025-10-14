import json
import boto3
import os
from datetime import datetime
import time
import random
import urllib.request
import urllib.parse
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email import encoders

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses')
bedrock = boto3.client('bedrock-runtime')

SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', 'xoxb-your-token-here')

# Confluence credentials
CONFLUENCE_EMAIL = "mdenecke@dairy.com"
CONFLUENCE_API_TOKEN = os.environ.get('CONFLUENCE_API_TOKEN', '')
CONFLUENCE_BASE_URL = "https://everag.atlassian.net/wiki"

# Simple in-memory conversation tracking with full history
user_conversations = {}

# Distribution list approval tracking
pending_approvals = {}
IT_APPROVAL_CHANNEL = "G016LL60F2L"  # IT channel ID
IT_APPROVAL_CHANNEL = "G016LL60F2L"  # IT channel ID

def detect_distribution_list_request(message):
    """Detect if user is requesting to be added to a distribution list"""
    keywords = [
        'add me to', 'distribution list', 'distro list', 'dl', 'mailing list',
        'email group', 'add to group', 'join group', 'subscribe to'
    ]
    
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)

def extract_distribution_list_name(message):
    """Extract the distribution list name from the message"""
    import re
    
    # Look for patterns like "add me to [list name]"
    patterns = [
        r'add me to (.+?)(?:\s|$)',
        r'distribution list (.+?)(?:\s|$)',
        r'distro list (.+?)(?:\s|$)',
        r'mailing list (.+?)(?:\s|$)',
        r'email group (.+?)(?:\s|$)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            return match.group(1).strip()
    
    return "unknown list"

def send_approval_request(user_id, user_name, user_email, distribution_list, original_message):
    """Send approval request to IT channel"""
    approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
    
    # Store pending approval
    pending_approvals[approval_id] = {
        'user_id': user_id,
        'user_name': user_name,
        'user_email': user_email,
        'distribution_list': distribution_list,
        'original_message': original_message,
        'timestamp': datetime.now().isoformat()
    }
    
    # Create approval message with buttons
    approval_message = {
        "channel": IT_APPROVAL_CHANNEL,
        "text": f"Distribution List Access Request",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Distribution List Access Request*\n\n*User:* {user_name}\n*Email:* {user_email}\n*Requested List:* `{distribution_list}`\n*Original Message:* {original_message}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Approve"
                        },
                        "style": "primary",
                        "action_id": f"approve_{approval_id}"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Deny"
                        },
                        "style": "danger",
                        "action_id": f"deny_{approval_id}"
                    }
                ]
            }
        ]
    }
    
    # Send to Slack
    send_slack_message(approval_message)
    
    return approval_id

def handle_approval_response(action_id, user_id):
    """Handle approval/denial response from IT team"""
    
    if action_id.startswith('approve_'):
        approval_id = action_id.replace('approve_', '')
        
        if approval_id in pending_approvals:
            approval_data = pending_approvals[approval_id]
            
            # Notify user of approval
            success_message = f"✅ Your distribution list request has been approved! Please contact IT to complete the process."
            
            headers = {
                'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                'Content-Type': 'application/json'
            }
            
            data = json.dumps({
                "channel": approval_data['user_id'],
                "text": success_message
            }).encode('utf-8')
            
            req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
            
            try:
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    print(f"Approval notification sent: {result}")
            except Exception as e:
                print(f"Error sending approval notification: {e}")
            
            # Clean up
            del pending_approvals[approval_id]
            
    elif action_id.startswith('deny_'):
        approval_id = action_id.replace('deny_', '')
        
        if approval_id in pending_approvals:
            approval_data = pending_approvals[approval_id]
            
            # Notify user of denial
            denial_message = f"❌ Your distribution list request has been denied. Please contact IT for more information."
            
            headers = {
                'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                'Content-Type': 'application/json'
            }
            
            data = json.dumps({
                "channel": approval_data['user_id'],
                "text": denial_message
            }).encode('utf-8')
            
            req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
            
            try:
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    print(f"Denial notification sent: {result}")
            except Exception as e:
                print(f"Error sending denial notification: {e}")
            
            # Clean up
            del pending_approvals[approval_id]

def send_slack_message(message_data):
    """Send message to Slack"""
    headers = {
        'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    data = json.dumps(message_data).encode('utf-8')
    req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return None

def extract_distribution_list_name(message):
    """Extract the distribution list name from the message"""
    import re
    
    # Look for patterns like "add me to [list name]"
    patterns = [
        r'add me to (.+?)(?:\s|$)',
        r'distribution list (.+?)(?:\s|$)',
        r'distro list (.+?)(?:\s|$)',
        r'mailing list (.+?)(?:\s|$)',
        r'email group (.+?)(?:\s|$)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            return match.group(1).strip()
    
    return "IT email list"

def send_approval_request(user_id, user_name, user_email, distribution_list, original_message):
    """Send approval request to IT channel"""
    approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
    
    # Store pending approval
    pending_approvals[approval_id] = {
        'user_id': user_id,
        'user_name': user_name,
        'user_email': user_email,
        'distribution_list': distribution_list,
        'original_message': original_message,
        'timestamp': datetime.now().isoformat()
    }
    
    # Create approval message with buttons
    approval_message = {
        "channel": IT_APPROVAL_CHANNEL,
        "text": f"Distribution List Access Request",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Distribution List Access Request*\n\n*User:* {user_name}\n*Email:* {user_email}\n*Requested List:* `{distribution_list}`\n*Original Message:* {original_message}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Approve"
                        },
                        "style": "primary",
                        "action_id": f"approve_{approval_id}"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Deny"
                        },
                        "style": "danger",
                        "action_id": f"deny_{approval_id}"
                    }
                ]
            }
        ]
    }
    
    # Send to Slack
    send_slack_message_to_channel(approval_message)
    
    return approval_id

def send_slack_message_to_channel(message_data):
    """Send message to Slack channel"""
    headers = {
        'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    data = json.dumps(message_data).encode('utf-8')
    req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return None

def handle_approval_response(action_id, user_id):
    """Handle approval/denial response from IT team"""
    
    if action_id.startswith('approve_'):
        approval_id = action_id.replace('approve_', '')
        
        if approval_id in pending_approvals:
            approval_data = pending_approvals[approval_id]
            
            # Notify user of approval
            success_message = f"✅ Your request to join `{approval_data['distribution_list']}` has been approved! Please contact IT to complete the process."
            send_slack_message_to_channel({
                "channel": approval_data['user_id'],
                "text": success_message
            })
            
            # Notify IT channel
            send_slack_message_to_channel({
                "channel": IT_APPROVAL_CHANNEL,
                "text": f"✅ Approved: {approval_data['user_name']} → `{approval_data['distribution_list']}`"
            })
            
            # Clean up
            del pending_approvals[approval_id]
            
    elif action_id.startswith('deny_'):
        approval_id = action_id.replace('deny_', '')
        
        if approval_id in pending_approvals:
            approval_data = pending_approvals[approval_id]
            
            # Notify user of denial
            denial_message = f"❌ Your request to join `{approval_data['distribution_list']}` has been denied. Please contact IT for more information."
            send_slack_message_to_channel({
                "channel": approval_data['user_id'],
                "text": denial_message
            })
            
            # Clean up
            del pending_approvals[approval_id]

def track_user_message(user_id, message, is_bot_response=False, image_url=None):
    """Track user's messages and bot responses for full conversation history"""
    if user_id not in user_conversations:
        user_conversations[user_id] = []
    
    message_entry = {
        'message': message,
        'timestamp': datetime.now().isoformat(),
        'is_bot': is_bot_response
    }
    
    # Add image URL if provided
    if image_url:
        message_entry['image_url'] = image_url
        message_entry['has_image'] = True
    
    user_conversations[user_id].append(message_entry)
    
    # Keep last 10 messages for full conversation context
    if len(user_conversations[user_id]) > 10:
        user_conversations[user_id] = user_conversations[user_id][-10:]

def get_conversation_context(user_id):
    """Get user's recent conversation for ticket context"""
    if user_id in user_conversations and user_conversations[user_id]:
        for msg in reversed(user_conversations[user_id]):
            if not msg['is_bot'] and not any(word in msg['message'].lower() for word in ['create ticket', 'ticket', 'escalate']):
                return msg['message']
    return None

def get_full_conversation_history(user_id):
    """Get complete conversation history for ticket"""
    if user_id not in user_conversations:
        return "No previous conversation history"
    
    conversation = []
    for msg in user_conversations[user_id]:
        if not any(word in msg['message'].lower() for word in ['create ticket', 'ticket', 'escalate']):
            if msg['is_bot']:
                conversation.append(f"Bot: {msg['message']}")
            else:
                if msg.get('has_image'):
                    conversation.append(f"User: {msg['message']} [SCREENSHOT: {msg.get('image_url', 'Image attached')}]")
                else:
                    conversation.append(f"User: {msg['message']}")
    
    return "\n\n".join(conversation) if conversation else "No previous conversation history"

def download_slack_image(image_url):
    """Download image from Slack and return base64 encoded data"""
    try:
        print(f"Attempting to download image from: {image_url}")
        headers = {'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
        req = urllib.request.Request(image_url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"Response status: {response.status}")
            if response.status == 200:
                image_data = response.read()
                print(f"Downloaded {len(image_data)} bytes")
                if len(image_data) > 0:
                    b64_data = base64.b64encode(image_data).decode('utf-8')
                    print(f"Encoded to base64: {len(b64_data)} characters")
                    return b64_data
                else:
                    print("Downloaded image is empty")
            else:
                print(f"HTTP error: {response.status}")
    except Exception as e:
        print(f"Error downloading image: {str(e)}")
    return None

def get_confluence_content():
    """Fetch content from Confluence pages with foritchatbot label"""
    try:
        # Create authentication header
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        # Search for pages with foritchatbot label
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/search?cql=label=foritchatbot&expand=body.storage"
        
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        req.add_header('Accept', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            confluence_knowledge = []
            for page in data.get('results', []):
                title = page.get('title', '')
                content = page.get('body', {}).get('storage', {}).get('value', '')
                
                # Clean up HTML content (basic cleanup)
                import re
                clean_content = re.sub(r'<[^>]+>', '', content)
                clean_content = re.sub(r'\s+', ' ', clean_content).strip()
                
                confluence_knowledge.append(f"TITLE: {title}\nCONTENT: {clean_content}")
            
            return "\n\n---\n\n".join(confluence_knowledge)
            
    except Exception as e:
        print(f"Error fetching Confluence content: {e}")
        return ""

def send_slack_message(channel, text):
    """Send message to Slack using Web API"""
    try:
        url = 'https://slack.com/api/chat.postMessage'
        data = {
            'channel': channel,
            'text': text,
            'as_user': True
        }
        
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode('utf-8'), 
            headers=headers
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('ok', False)
            
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return False

def get_user_info_from_slack(user_id):
    """Get user name and email from Slack profile"""
    try:
        url = f'https://slack.com/api/users.info'
        data = {'user': user_id}
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data, headers=headers)
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('ok') and 'user' in result:
                user_info = result['user']
                profile = user_info.get('profile', {})
                
                real_name = user_info.get('real_name', '') or profile.get('real_name', '') or profile.get('display_name', '')
                email = profile.get('email')
                
                if email and '@' in email:
                    print(f"Found email for user {user_id}: {email}")
                else:
                    if real_name and ' ' in real_name:
                        name_parts = real_name.strip().split()
                        first_name = name_parts[0].lower()
                        last_name = name_parts[-1].lower()
                        email = f"{first_name}.{last_name}@ever.ag"
                        print(f"No email in profile, generated: {email}")
                    else:
                        email = f"user.{user_id}@ever.ag"
                
                return real_name or f"user_{user_id}", email
            else:
                return f"user_{user_id}", f"user.{user_id}@ever.ag"
                
    except Exception as e:
        print(f"Error getting user info: {e}")
        return f"user_{user_id}", f"user.{user_id}@ever.ag"

def log_interaction_to_dynamodb(user_id, user_name, user_message, bot_response):
    """Log interaction to Recent Interactions table"""
    try:
        table = dynamodb.Table('recent-interactions')
        table.put_item(Item={
            'user_id': user_id,
            'timestamp': int(time.time()),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response
        })
    except Exception as e:
        print(f"Error logging interaction: {e}")

def save_ticket_to_dynamodb(user_id, user_name, user_email, issue_description, previous_question=None):
    """Save ticket to DynamoDB and send email with conversation context"""
    try:
        table = dynamodb.Table('it-helpdesk-tickets')
        
        # Get full conversation history
        conversation_history = get_full_conversation_history(user_id)
        
        full_description = issue_description
        if previous_question:
            full_description = f"Previous Question: {previous_question}\n\nEscalation Request: {issue_description}"
        
        timestamp = int(datetime.now().timestamp())
        ticket_id = f"{user_id}_{timestamp}"
        
        item = {
            'ticket_id': ticket_id,
            'user_id': user_id,
            'user_name': user_name,
            'user_email': user_email,
            'issue_description': full_description,
            'conversation_history': conversation_history,
            'previous_question': previous_question or '',
            'status': 'OPEN',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        table.put_item(Item=item)
        
        # Send email notification with full conversation history and images
        try:
            subject = f"IT Support Request from {user_name}"
            
            # Enhanced email body with complete conversation
            body = f"""
New IT Support Request

Submitted by: {user_name}
Email: {user_email}

"""
            
            # Collect images from conversation
            attachments = []
            print(f"Checking for images in conversation for user {user_id}")
            if user_id in user_conversations:
                print(f"Found {len(user_conversations[user_id])} messages in conversation")
                for i, msg in enumerate(user_conversations[user_id]):
                    print(f"Message {i}: has_image={msg.get('has_image')}, image_url={msg.get('image_url')}")
                    if msg.get('has_image') and msg.get('image_url'):
                        print(f"Downloading image: {msg['image_url']}")
                        image_data = download_slack_image(msg['image_url'])
                        if image_data:
                            # Determine file extension from URL
                            file_ext = 'png'
                            if '.jpg' in msg['image_url'] or '.jpeg' in msg['image_url']:
                                file_ext = 'jpg'
                            elif '.gif' in msg['image_url']:
                                file_ext = 'gif'
                            
                            attachments.append({
                                'filename': f"screenshot_{i+1}.{file_ext}",
                                'data': image_data,
                                'content_type': f'image/{file_ext}'
                            })
                            print(f"Added attachment: screenshot_{i+1}.{file_ext}")
                        else:
                            print("Failed to download image data")
            else:
                print("No conversation history found for user")
            
            print(f"Total attachments: {len(attachments)}")
            
            if conversation_history and conversation_history != "No previous conversation history":
                body += f"""FULL CONVERSATION HISTORY:
{conversation_history}

Escalation Request: User requested ticket to be opened

End User Response: User tried suggested solutions but issue persists, requesting human support
"""
            else:
                body += f"""Issue Description: {issue_description}

Escalation Request: User requested ticket to be opened
"""
            
            body += f"""
Contact Information: {user_email}

This request was created via the IT Helpdesk Slack Bot.
Reply directly to this email to respond to the user.
            """
            
            # Send via SES with attachments
            if attachments:
                # Create multipart message with attachments
                msg = MIMEMultipart()
                msg['From'] = user_email
                msg['To'] = 'matthew.denecke@ever.ag'
                msg['Subject'] = subject
                
                # Add body
                msg.attach(MIMEText(body, 'plain'))
                
                # Add attachments
                for attachment in attachments:
                    # Decode base64 to get raw image bytes
                    image_bytes = base64.b64decode(attachment['data'])
                    # Create proper image attachment
                    img = MIMEImage(image_bytes)
                    img.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{attachment["filename"]}"'
                    )
                    msg.attach(img)
                
                # Send email
                ses.send_raw_email(
                    Source=user_email,
                    Destinations=['matthew.denecke@ever.ag'],
                    RawMessage={'Data': msg.as_string()}
                )
            else:
                # Send simple email without attachments
                ses.send_email(
                    Source=user_email,
                    Destination={'ToAddresses': ['matthew.denecke@ever.ag']},
                    Message={
                        'Subject': {'Data': subject},
                        'Body': {'Text': {'Data': body}}
                    }
                )
        except Exception as e:
            print(f"Email error: {e}")
        
        return True
    except Exception as e:
        print(f"Error saving ticket: {e}")
        return False

def analyze_image_with_claude(image_url, user_message):
    """Analyze uploaded image using Claude Vision"""
    try:
        print(f"Attempting to analyze image: {image_url}")
        
        # Try to download the image from Slack
        headers = {'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
        req = urllib.request.Request(image_url, headers=headers)
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status != 200:
                    print(f"HTTP error downloading image: {response.status}")
                    return "I can see you uploaded an image, but I'm having trouble downloading it from Slack. Please describe what the image shows."
                
                image_data = response.read()
                print(f"Successfully downloaded image, size: {len(image_data)} bytes")
                
                if len(image_data) == 0:
                    print("Downloaded image is empty")
                    return "The image appears to be empty. Please try uploading it again or describe what it shows."
                
                image_b64 = base64.b64encode(image_data).decode('utf-8')
                
        except urllib.error.HTTPError as e:
            print(f"HTTP error downloading image: {e.code} - {e.reason}")
            return "I can see you uploaded an image, but I don't have permission to access it. Please describe what the image shows."
        except Exception as e:
            print(f"Error downloading image: {e}")
            return "I can see you uploaded an image, but I'm having trouble downloading it. Please describe what the image shows."
        
        # Determine image type from URL or default to PNG
        if '.jpg' in image_url or '.jpeg' in image_url:
            media_type = "image/jpeg"
        elif '.png' in image_url:
            media_type = "image/png"
        elif '.gif' in image_url:
            media_type = "image/gif"
        elif '.webp' in image_url:
            media_type = "image/webp"
        else:
            media_type = "image/png"  # Default
        
        print(f"Using media type: {media_type}")
        
        # Prepare Claude Vision request
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"User message: {user_message}\n\nPlease analyze this image and extract any relevant technical information. If it's a speed test, provide the download/upload speeds and ping. If it's an error message, describe the error. If it's a network configuration, summarize the key details."
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64
                            }
                        }
                    ]
                }
            ]
        }
        
        print("Sending image to Claude for analysis...")
        
        # Call Claude Vision via Bedrock
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text']
        
        print(f"Claude analysis successful: {analysis[:100]}...")
        return analysis
        
    except Exception as e:
        print(f"Error analyzing image: {e}")
        error_msg = str(e)
        if "ValidationException" in error_msg:
            return "I can see you uploaded an image, but MattBot is having trouble processing it. This might be due to the image format or size. Please describe what the image shows so I can help you."
        elif "AccessDenied" in error_msg:
            return "I can see you uploaded an image, but I don't have permission to analyze it. Please describe what the image shows."
        else:
            return "I can see you uploaded an image, but I'm having trouble analyzing it right now. Please describe what the image shows."
        
        # Call Claude Vision via Bedrock
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text']
        
        return analysis
        
    except Exception as e:
        print(f"Error analyzing image: {e}")
        return "I can see you uploaded an image, but I'm having trouble analyzing it right now. Please describe what the image shows."

def get_claude_response(user_message, user_name, image_analysis=None):
    """Get response from Claude Sonnet 4 with Confluence knowledge and optional image analysis"""
    try:
        # Get Confluence content
        confluence_content = get_confluence_content()
        
        # Ever.Ag specific knowledge base
        company_info = f"""
Ever.Ag Company IT Information:

PASSWORD RESET:
- Call IT Support: 214-807-0784 (emergencies only)
- Or users can create a ticket by saying "create ticket"

IT SUPPORT CONTACT:
- Email: itsupport@ever.ag  
- Phone: 214-807-0784 (emergencies only)

GENERAL POLICIES:
- Company uses Microsoft Office 365
- Email domain: @ever.ag
- Standard business hours support

CONFLUENCE KNOWLEDGE BASE:
{confluence_content}
        """
        
        # Include image analysis if available
        message_content = f"User {user_name} asks: {user_message}"
        if image_analysis:
            message_content += f"\n\nImage Analysis: {image_analysis}"
        
        system_prompt = f"""You are an IT helpdesk assistant for Ever.Ag. You help employees with technical issues.

{company_info}

IMPORTANT INSTRUCTIONS:
1. Use the Confluence knowledge base above to provide accurate, company-specific troubleshooting steps
2. If image analysis is provided, incorporate those details into your response
3. For speed test results, comment on whether speeds are normal or concerning
4. If user asks about password reset, tell them to call 214-807-0784 (emergencies only) or say "create ticket"
5. For ticket creation, tell them to say "create ticket" 
6. Provide specific, actionable troubleshooting steps from the knowledge base
7. Be concise but helpful
8. Use emojis to make responses friendly
9. If you don't know something specific to Ever.Ag, provide general IT help and suggest contacting IT support

Always be helpful and professional. Reference the specific procedures from the Confluence documentation when applicable."""

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": message_content
                }
            ]
        }
        
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        claude_response = response_body['content'][0]['text']
        
        return claude_response
        
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return """I'm having trouble processing your request right now. 

For immediate help:
• **Password issues:** Call IT Support at 214-807-0784 (emergencies only)
• **Other IT issues:** Say "create ticket" to reach IT support
• **Email:** itsupport@ever.ag

I'll be back online shortly!"""

def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"Received event: {json.dumps(event)}")
    
    try:
        if 'body' in event:
            # Try to parse as JSON first
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                # Handle URL-encoded payloads (button clicks)
                if 'payload=' in event.get('body', ''):
                    parsed_body = urllib.parse.parse_qs(event['body'])
                    if 'payload' in parsed_body:
                        payload = json.loads(parsed_body['payload'][0])
                        
                        if payload.get('type') == 'block_actions':
                            action_id = payload.get('actions', [{}])[0].get('action_id', '')
                            user_id = payload.get('user', {}).get('id', '')
                            
                            print(f"Button clicked: {action_id} by user {user_id}")
                            
                            if action_id.startswith(('approve_', 'deny_')):
                                handle_approval_response(action_id, user_id)
                                return {'statusCode': 200, 'body': 'OK'}
                
                return {'statusCode': 200, 'body': 'OK'}
            
            if body.get('type') == 'url_verification':
                return {
                    'statusCode': 200,
                    'headers': {'Content-Type': 'text/plain'},
                    'body': body['challenge']
                }
            
            # Handle interactive components (button clicks)
            if body.get('type') == 'interactive':
                payload = body.get('payload', {})
                if isinstance(payload, str):
                    payload = json.loads(payload)
                
                action_id = payload.get('actions', [{}])[0].get('action_id', '')
                user_id = payload.get('user', {}).get('id', '')
                
                if action_id.startswith(('approve_', 'deny_')):
                    handle_approval_response(action_id, user_id)
                    return {'statusCode': 200, 'body': 'OK'}
            
            # Handle interactive components (button clicks)
            if body.get('type') == 'interactive':
                payload = body.get('payload', {})
                if isinstance(payload, str):
                    payload = json.loads(payload)
                
                action_id = payload.get('actions', [{}])[0].get('action_id', '')
                user_id = payload.get('user', {}).get('id', '')
                
                if action_id.startswith(('approve_', 'deny_')):
                    handle_approval_response(action_id, user_id)
                    return {'statusCode': 200, 'body': 'OK'}
            
            if body.get('type') == 'event_callback':
                slack_event = body['event']
                
                # Comprehensive bot message filtering to prevent loops
                if (slack_event.get('subtype') == 'bot_message' or 
                    'bot_id' in slack_event or 
                    slack_event.get('user') == 'U09CEF9E5QB' or
                    slack_event.get('subtype') == 'message_changed' or
                    slack_event.get('subtype') == 'message_deleted'):
                    print(f"Ignoring bot/system message: {slack_event.get('subtype', 'bot_message')}")
                    return {'statusCode': 200, 'body': 'OK'}
                
                if slack_event['type'] == 'message':
                    user_id = slack_event.get('user')
                    user_name = f"user_{user_id}" if user_id else "Unknown"
                    message = slack_event.get('text', '')
                    channel = slack_event.get('channel')
                    
                    # Log the full event for debugging
                    print(f"Full Slack event: {json.dumps(slack_event)}")
                    
                    # Check for image uploads in multiple possible locations
                    files = slack_event.get('files', [])
                    image_url = None
                    image_detected = False
                    
                    # Method 1: Direct files array
                    if files:
                        print(f"Found files array: {files}")
                        for file in files:
                            print(f"File details: {file}")
                            if file.get('mimetype', '').startswith('image/'):
                                image_detected = True
                                # Try thumbnail URLs first (more likely to be accessible), then private URLs
                                for url_field in ['thumb_720', 'thumb_480', 'thumb_360', 'permalink_public', 'url_private_download', 'url_private']:
                                    if file.get(url_field):
                                        image_url = file[url_field]
                                        print(f"Found image URL via {url_field}: {image_url}")
                                        break
                                if image_url:
                                    break
                    
                    # Method 2: Check if this is a file_share subtype
                    if not image_url and slack_event.get('subtype') == 'file_share':
                        image_detected = True  # We know an image was shared
                        file_info = slack_event.get('file', {})
                        print(f"File share detected: {file_info}")
                        if file_info.get('mimetype', '').startswith('image/'):
                            # Try thumbnail URLs first (more likely to be accessible), then private URLs
                            for url_field in ['thumb_720', 'thumb_480', 'thumb_360', 'permalink_public', 'url_private_download', 'url_private']:
                                if file_info.get(url_field):
                                    image_url = file_info[url_field]
                                    print(f"Found image URL via {url_field}: {image_url}")
                                    break
                    
                    # Method 3: Check attachments
                    if not image_url:
                        attachments = slack_event.get('attachments', [])
                        if attachments:
                            print(f"Found attachments: {attachments}")
                            for attachment in attachments:
                                if attachment.get('image_url'):
                                    image_detected = True
                                    image_url = attachment.get('image_url')
                                    print(f"Found image in attachments: {image_url}")
                                    break
                    
                    print(f"Processing message from {user_name}: {message}")
                    if image_url:
                        print(f"Image detected with URL: {image_url}")
                    elif image_detected:
                        print("Image detected but URL not accessible")
                    else:
                        print("No image detected in this message")
                    
                    # Track message for conversation context (include image URL if present)
                    if image_detected and image_url:
                        track_user_message(user_id, message, image_url=image_url)
                    else:
                        track_user_message(user_id, message)
                    message_lower = message.lower()
                    
                    # Check for ticket creation FIRST - don't process with Claude if creating ticket
                    if any(word in message_lower for word in ['create ticket', 'ticket', 'escalate', 'human support']):
                        real_name, user_email = get_user_info_from_slack(user_id)
                        previous_question = get_conversation_context(user_id)
                        
                        if save_ticket_to_dynamodb(user_id, real_name, user_email, message, previous_question):
                            response = f"""✅ **Support Request Submitted**

**Submitted by:** {real_name}
**From Email:** {user_email}
**Status:** Sent to matthew.denecke@ever.ag (temporary for testing)"""
                            
                            if previous_question:
                                response += f"\n**Context:** Included your previous question about: \"{previous_question[:50]}...\""
                            
                            response += "\n\nYour request has been submitted to IT Support.\nThey can reply directly to your email: " + user_email
                            
                            send_slack_message(channel, f"🔧 {response}")
                        else:
                            send_slack_message(channel, "🔧 ❌ Error submitting request. Please try again or call IT Support at 214-807-0784 (emergencies only).")
                        
                        # Return immediately - don't continue to Claude processing
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for distribution list requests
                    elif any(word in message_lower for word in ['add me to', 'distribution list', 'distro list', 'email group']):
                        real_name, user_email = get_user_info_from_slack(user_id)
                        
                        # Send approval request with buttons to IT channel
                        approval_id = f"dl_approval_{user_id}_{int(datetime.now().timestamp())}"
                        
                        # Store pending approval
                        pending_approvals[approval_id] = {
                            'user_id': user_id,
                            'user_name': real_name,
                            'user_email': user_email,
                            'message': message,
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        headers = {
                            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
                            'Content-Type': 'application/json'
                        }
                        
                        approval_message = {
                            "channel": "G016LL60F2L",
                            "text": f"Distribution List Access Request",
                            "blocks": [
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": f"*Distribution List Access Request*\n\n*User:* {real_name}\n*Email:* {user_email}\n*Message:* {message}"
                                    }
                                },
                                {
                                    "type": "actions",
                                    "elements": [
                                        {
                                            "type": "button",
                                            "text": {
                                                "type": "plain_text",
                                                "text": "Approve"
                                            },
                                            "style": "primary",
                                            "action_id": f"approve_{approval_id}"
                                        },
                                        {
                                            "type": "button",
                                            "text": {
                                                "type": "plain_text",
                                                "text": "Deny"
                                            },
                                            "style": "danger",
                                            "action_id": f"deny_{approval_id}"
                                        }
                                    ]
                                }
                            ]
                        }
                        
                        data = json.dumps(approval_message).encode('utf-8')
                        
                        req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
                        
                        try:
                            with urllib.request.urlopen(req) as response:
                                result = json.loads(response.read().decode())
                                print(f"IT notification sent: {result}")
                        except Exception as e:
                            print(f"Error sending IT notification: {e}")
                        
                        # Respond to user
                        send_slack_message(channel, "📧 I've received your distribution list request and notified the IT team. They'll review it and get back to you!")
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for distribution list requests
                    elif any(word in message_lower for word in ['add me to', 'distribution list', 'distro list', 'email group']):
                        print(f"Distribution list request detected: {message}")
                        real_name, user_email = get_user_info_from_slack(user_id)
                        distribution_list = extract_distribution_list_name(message)
                        
                        # Send approval request to IT channel
                        approval_id = send_approval_request(user_id, real_name, user_email, distribution_list, message)
                        
                        # Respond to user
                        response = f"""📧 **Distribution List Request Received**

**Requested List:** `{distribution_list}`
**Status:** Pending IT approval

I've sent your request to the IT team for approval. You'll be notified once they review it!"""
                        
                        send_slack_message(channel, response)
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    # Check for distribution list requests
                    elif detect_distribution_list_request(message):
                        print(f"Distribution list request detected: {message}")
                        real_name, user_email = get_user_info_from_slack(user_id)
                        distribution_list = extract_distribution_list_name(message)
                        
                        # Send approval request to IT channel
                        approval_id = send_approval_request(user_id, real_name, user_email, distribution_list, message)
                        
                        # Respond to user
                        response = f"""📧 **Distribution List Request Received**

**Requested List:** `{distribution_list}`
**Status:** Pending IT approval

I've sent your request to the IT team for approval. You'll be notified once they review it!"""
                        
                        send_slack_message(channel, response)
                        return {'statusCode': 200, 'body': 'OK'}
                    
                    else:
                        # For Claude questions, send immediate response and return quickly to prevent retries
                        if image_detected:
                            if image_url:
                                send_slack_message(channel, "🔧 🤔 I can see you uploaded an image! Let me analyze it and get back to you...")
                            else:
                                send_slack_message(channel, "🔧 🤔 I can see you uploaded an image, but I'm having trouble accessing it. Let me help you anyway...")
                        else:
                            send_slack_message(channel, "🔧 🤔 Let me think about that... I'll have an answer for you in just a moment!")
                        
                        # Return immediately to Slack to prevent retries
                        # Then invoke async processing
                        lambda_client = boto3.client('lambda')
                        async_payload = {
                            'async_processing': True,
                            'user_message': message,
                            'user_name': user_name,
                            'user_id': user_id,
                            'channel': channel,
                            'image_url': image_url,
                            'image_detected': image_detected
                        }
                        
                        # Start async processing but don't wait for it
                        try:
                            lambda_client.invoke(
                                FunctionName=context.function_name,
                                InvocationType='Event',  # Async invocation
                                Payload=json.dumps(async_payload)
                            )
                        except Exception as e:
                            print(f"Error invoking async processing: {e}")
                        
                        # Return immediately to prevent Slack retries
                        return {'statusCode': 200, 'body': 'OK'}
        
        # Handle async processing
        elif event.get('async_processing'):
            user_message = event['user_message']
            user_name = event['user_name']
            channel = event['channel']
            user_id = event.get('user_id', 'unknown')
            image_url = event.get('image_url')
            image_detected = event.get('image_detected', False)
            
            print(f"Async processing for: {user_message}")
            
            # Send follow-up message
            import time
            time.sleep(8)
            
            image_analysis = None
            
            if image_url:
                followup_msg = "🤔 Still analyzing your image... MattBot is examining the details!"
                send_slack_message(channel, followup_msg)
                
                # Analyze the image
                image_analysis = analyze_image_with_claude(image_url, user_message)
                print(f"Image analysis: {image_analysis}")
            elif image_detected:
                # Image was detected but URL not accessible
                followup_msg = "🤔 I can see you uploaded an image, but I'm having trouble accessing it. Let me help you anyway!"
                send_slack_message(channel, followup_msg)
                
                # Add a note about the image issue
                image_analysis = "User uploaded an image/screenshot but the bot couldn't access the file URL. Please ask the user to describe what the image shows so you can provide appropriate help."
            else:
                # Check if user mentioned uploading an image but we couldn't detect it
                if any(word in user_message.lower() for word in ['screenshot', 'image', 'picture', 'attached', 'upload']):
                    followup_msg = "🤔 I can see you mentioned an image, but I'm having trouble accessing it. Let me help you anyway!"
                    send_slack_message(channel, followup_msg)
                    
                    # Add a note about the image issue
                    image_analysis = "User mentioned uploading an image/screenshot but the bot couldn't detect or access the file. Ask user to describe what the image shows."
                else:
                    followup_msg = "🤔 Still working on your question... MattBot is analyzing the best solution for you!"
                    send_slack_message(channel, followup_msg)
            
            # Get Claude response with Confluence knowledge and optional image analysis
            claude_response = get_claude_response(user_message, user_name, image_analysis)
            send_slack_message(channel, f"🔧 {claude_response}")
            
            # Track the bot's response in conversation history
            if image_analysis:
                full_response = f"{claude_response}\n\n[Image Analysis: {image_analysis}]"
                track_user_message(user_id, full_response, is_bot_response=True)
            else:
                track_user_message(user_id, claude_response, is_bot_response=True)
            
            # Log interaction to DynamoDB
            log_interaction_to_dynamodb(user_id, user_name, user_message, claude_response)
            
            print(f"Sent Claude response to Slack")
        
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 200, 'body': 'OK'}
