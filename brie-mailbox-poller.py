import json
import boto3
import re
import base64
import urllib.request
import urllib.parse
import os
import io
import uuid

# Initialize AWS clients
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')
textract_client = boto3.client('textract', region_name='us-east-1')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

from datetime import datetime

# Initialize AWS Bedrock for Claude
bedrock = boto3.client('bedrock-runtime')

# Email logging table
try:
    email_log_table = dynamodb.Table('brie-email-logs')
except:
    email_log_table = None
    print("⚠️ Email logging table not available")

# Confluence credentials
CONFLUENCE_EMAIL = "mdenecke@dairy.com"
CONFLUENCE_API_TOKEN = "ATLASSIAN_API_TOKEN=A2D8BE4C"

def log_email_processing(message_id, sender, subject, body, detection_step, claude_analysis, action_taken, response_sent=None, attachments_info=None):
    """Log comprehensive email processing details"""
    try:
        # Generate unique log ID
        log_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # Prepare email data for S3
        email_data = {
            'log_id': log_id,
            'timestamp': timestamp,
            'message_id': message_id,
            'sender': sender,
            'subject': subject,
            'body': body,
            'detection_step': detection_step,
            'claude_analysis': claude_analysis,
            'action_taken': action_taken,
            'response_sent': response_sent,
            'attachments_info': attachments_info or []
        }
        
        # Store full email in S3
        s3_key = f"email-logs/{timestamp[:10]}/{log_id}.json"
        try:
            s3_client.put_object(
                Bucket='brie-email-archive',
                Key=s3_key,
                Body=json.dumps(email_data, indent=2),
                ContentType='application/json'
            )
        except Exception as s3_error:
            print(f"⚠️ S3 logging failed: {s3_error}")
        
        # Store searchable record in DynamoDB
        if email_log_table:
            try:
                email_log_table.put_item(
                    Item={
                        'log_id': log_id,
                        'timestamp': timestamp,
                        'date': timestamp[:10],
                        'message_id': message_id,
                        'sender': sender,
                        'subject': subject,
                        'detection_step': detection_step,
                        'action_taken': action_taken,
                        's3_location': s3_key,
                        'has_attachments': len(attachments_info or []) > 0,
                        'claude_analysis_length': len(claude_analysis or ''),
                        'response_sent': response_sent is not None
                    }
                )
            except Exception as db_error:
                print(f"⚠️ DynamoDB logging failed: {db_error}")
        
        print(f"📝 Email logged: {log_id[:8]} - {detection_step} - {action_taken}")
        return log_id
        
    except Exception as e:
        print(f"❌ Error logging email: {e}")
        return None
CONFLUENCE_BASE_URL = "https://everag.atlassian.net/wiki"
CONFLUENCE_SPACE_KEY = "IT"

# Office 365 credentials (same as existing email-monitor)
TENANT_ID = "3d90a358-2976-40f4-8588-45ed47a26302"
CLIENT_ID = "97d0a776-cc4a-4c2d-a774-fba7c66938f7"
CLIENT_SECRET = os.environ.get('CLIENT_SECRET', 'AZURE_CLIENT_SECRET')
MAILBOX_EMAIL = "brieitagent@ever.ag"

def analyze_ticket_with_claude(subject, description, sender_email):
    """Use Claude to analyze if ticket has sufficient details for troubleshooting"""
    try:
        system_prompt = """You are an IT support ticket analyzer. 

RESPOND WITH ONLY ONE WORD: Either "SUFFICIENT" or "INSUFFICIENT"

A ticket is SUFFICIENT if it has:
- Specific error messages/codes, OR
- Clear technical symptoms with context, OR  
- Specific applications with detailed problems

A ticket is INSUFFICIENT if it has:
- Vague complaints ("slow", "broken", "not working") without specifics
- No error details or technical information
- Very short descriptions without context

Examples:
"Outlook error 0x80040115" = SUFFICIENT
"Can't print to HP LaserJet" = SUFFICIENT  
"My computer is slow" = INSUFFICIENT
"Teams won't start" = INSUFFICIENT"""

        ticket_content = f"""
Subject: {subject}
Description: {description}
"""

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 10,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": f"Analyze this ticket:\n\n{ticket_content}"
                }
            ]
        }
        
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text'].strip().upper()
        
        print(f"Claude analysis: {analysis}")
        
        # Return True if sufficient, False if insufficient
        if analysis.strip() == "SUFFICIENT":
            print(f"Claude says SUFFICIENT, returning True")
            return True
        elif analysis.strip() == "INSUFFICIENT":
            print(f"Claude says INSUFFICIENT, returning False")
            return False
        else:
            print(f"Unexpected Claude response: {analysis}, using fallback")
            return is_ticket_detailed_enough_fallback(subject, description, sender_email)
        
    except Exception as e:
        print(f"Error calling Claude for ticket analysis: {e}")
        # Fallback to keyword-based logic if Claude fails
        return is_ticket_detailed_enough_fallback(subject, description, sender_email)

def is_ticket_detailed_enough_fallback(subject, description, sender_email):
    """Fallback logic if Claude is unavailable"""
    subject_lower = subject.lower() if subject else ""
    description_lower = description.lower() if description else ""
    combined_text = subject_lower + " " + description_lower
    
    # High-value indicators that make tickets sufficient
    high_value_indicators = [
        "error", "code", "0x", "exception", "failed", "timeout", 
        "cannot", "unable", "specific", "when i", "after i", "before i"
    ]
    
    # Check for high-value details
    has_high_value = any(indicator in combined_text for indicator in high_value_indicators)
    
    # Check for sufficient length
    has_length = len(description.strip()) > 50
    
    # Check for contact info
    has_contact = has_contact_info(sender_email, description)
    
    return has_high_value and has_length and has_contact

def get_access_token():
    """Get access token for Microsoft Graph API - exact same method as working email-monitor"""
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    
    data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default'
    }
    
    encoded_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(token_url, data=encoded_data)
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode('utf-8'))
        return result['access_token']

def get_unread_emails(access_token):
    """Get unread emails from brieitagent@ever.ag mailbox - using exact same pattern as working email-monitor"""
    try:
        # Use exact same URL encoding pattern as working email-monitor
        filter_param = urllib.parse.quote("isRead eq false")
        graph_url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX_EMAIL}/messages?$filter={filter_param}&$top=10"
        
        req = urllib.request.Request(graph_url)
        req.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            emails = result.get('value', [])
            return emails
    except Exception as e:
        print(f"Error getting emails: {e}")
        return []

def mark_email_as_read(access_token, message_id):
    """Mark email as read"""
    try:
        url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX_EMAIL}/messages/{message_id}"
        data = json.dumps({'isRead': True}).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='PATCH')
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            return response.status == 200
    except Exception as e:
        print(f"Error marking email as read: {e}")
        return False

def delete_email(access_token, message_id):
    """Delete email"""
    try:
        url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX_EMAIL}/messages/{message_id}"
        
        req = urllib.request.Request(url, method='DELETE')
        req.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(req) as response:
            return response.status == 204
    except Exception as e:
        print(f"Error deleting email: {e}")
        return False

def is_ticket_detailed_enough(subject, description, sender_email):
    """Use Claude AI to determine if ticket has sufficient details"""
    try:
        print(f"Calling Claude analysis for: {subject}")
        # First try Claude analysis
        result = analyze_ticket_with_claude(subject, description, sender_email)
        print(f"Claude analysis result: {result}")
        return result
    except Exception as e:
        print(f"Claude analysis failed, using fallback: {e}")
        # Fallback to rule-based logic
        return is_ticket_detailed_enough_fallback(subject, description, sender_email)

def has_contact_info(sender_email, description):
    """Check if we have proper contact information"""
    # Generic support emails don't count as contact info
    generic_emails = ["support@", "help@", "noreply@", "donotreply@", "itsupport@"]
    
    if any(generic in sender_email.lower() for generic in generic_emails):
        # Check if description contains contact info
        import re
        phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
        name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
        
        has_phone = bool(re.search(phone_pattern, description))
        has_name = bool(re.search(name_pattern, description))
        
        return has_phone or has_name
    
    return True  # Personal email addresses are fine

def get_email_attachments(access_token, message_id):
    """Get attachments from an email"""
    graph_url = f"https://graph.microsoft.com/v1.0/users/brieitagent@ever.ag/messages/{message_id}/attachments"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    req = urllib.request.Request(graph_url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            attachments_data = json.loads(response.read().decode('utf-8'))
            return attachments_data.get('value', [])
    except Exception as e:
        print(f"Error getting attachments: {e}")
        return []

def analyze_image_with_claude(image_data, image_format="image/png"):
    """Analyze image using Claude Vision for full context understanding"""
    try:
        # Convert image to base64 for Claude
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Prepare the request for Claude Vision
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_format,
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": """Analyze this screenshot for IT support purposes. Extract:

1. Any error messages (exact text)
2. What application/system is shown
3. What the user is trying to do
4. Any visible UI problems or issues
5. Context that would help IT support

Focus on technical details that would help diagnose IT issues. If there are error messages, include the exact text."""
                        }
                    ]
                }
            ]
        }
        
        response = bedrock_client.invoke_model(
            modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        analysis = response_body['content'][0]['text']
        
        return analysis
        
    except Exception as e:
        print(f"Error analyzing image with Claude Vision: {e}")
        # Fallback to OCR if Claude Vision fails
        return extract_text_from_image(image_data)

def extract_text_from_image(image_data):
    """Fallback OCR function using AWS Textract"""
    try:
        response = textract_client.detect_document_text(
            Document={'Bytes': image_data}
        )
        
        # Extract all text from the response
        extracted_text = []
        for block in response['Blocks']:
            if block['BlockType'] == 'LINE':
                extracted_text.append(block['Text'])
        
        return ' '.join(extracted_text)
    except Exception as e:
        print(f"Error extracting text from image: {e}")
        return ""

def extract_inline_images(email_body):
    """Extract inline images from email body HTML"""
    import re
    import base64
    
    inline_images = []
    
    if not email_body:
        return inline_images
    
    # Look for base64 encoded images in img tags
    base64_pattern = r'<img[^>]*src="data:image/([^;]+);base64,([^"]+)"[^>]*>'
    matches = re.findall(base64_pattern, email_body, re.IGNORECASE)
    
    for i, (image_format, base64_data) in enumerate(matches):
        try:
            # Validate base64 data
            image_bytes = base64.b64decode(base64_data)
            if len(image_bytes) > 0:
                inline_images.append({
                    'name': f'inline_image_{i+1}.{image_format}',
                    'format': f'image/{image_format}',
                    'data': base64_data,
                    'size': len(image_bytes)
                })
                print(f"Found inline image: inline_image_{i+1}.{image_format} ({len(image_bytes)} bytes)")
        except Exception as e:
            print(f"Error processing inline image {i+1}: {e}")
    
    return inline_images

def process_email_attachments(access_token, message_id, email_body=None):
    """Process email attachments and inline images, extract text from images"""
    print(f"Starting attachment processing for message ID: {message_id}")
    
    # Process formal attachments
    attachments = get_email_attachments(access_token, message_id)
    print(f"Found {len(attachments)} total attachments")
    
    # Process inline images from email body
    inline_images = []
    if email_body:
        inline_images = extract_inline_images(email_body)
        print(f"Found {len(inline_images)} inline images")
    
    extracted_texts = []
    
    for i, attachment in enumerate(attachments):
        print(f"Processing attachment {i+1}: {attachment.get('name', 'unknown')}")
        print(f"Content type: {attachment.get('contentType', 'unknown')}")
        print(f"Size: {attachment.get('size', 'unknown')} bytes")
        
        # Check if it's an image attachment (including Microsoft Graph octet-stream)
        content_type = attachment.get('contentType', '').lower()
        attachment_name = attachment.get('name', '').lower()
        
        print(f"Checking if '{content_type}' is an image...")
        
        # Check by content type OR file extension for images
        is_image_content_type = any(img_type in content_type for img_type in ['image/', 'png', 'jpg', 'jpeg', 'gif', 'bmp'])
        is_image_extension = any(attachment_name.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])
        is_octet_stream_image = (content_type == 'application/octet-stream' and 
                                (is_image_extension or 'img-' in attachment_name or 'image' in attachment_name))
        
        if is_image_content_type or is_image_extension or is_octet_stream_image:
            print(f"✅ Detected image attachment: {attachment['name']} (type: {content_type})")
            try:
                # Get the attachment content
                attachment_id = attachment['id']
                print(f"Getting attachment content for ID: {attachment_id}")
                
                graph_url = f"https://graph.microsoft.com/v1.0/users/brieitagent@ever.ag/messages/{message_id}/attachments/{attachment_id}"
                
                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                }
                
                req = urllib.request.Request(graph_url, headers=headers)
                with urllib.request.urlopen(req) as response:
                    attachment_data = json.loads(response.read().decode('utf-8'))
                    print(f"Successfully downloaded attachment data")
                    
                    # Decode the base64 content
                    content_bytes = base64.b64decode(attachment_data['contentBytes'])
                    print(f"Decoded {len(content_bytes)} bytes of image data")
                    
                    # Analyze image using Claude Vision for full context
                    print(f"Starting Claude Vision analysis...")
                    
                    # Try to determine actual image format for Claude Vision
                    # Check first few bytes to identify image type
                    image_format = "image/png"  # default
                    if content_bytes[:4] == b'\xff\xd8\xff\xe0' or content_bytes[:4] == b'\xff\xd8\xff\xe1':
                        image_format = "image/jpeg"
                    elif content_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                        image_format = "image/png"
                    elif content_bytes[:6] == b'GIF87a' or content_bytes[:6] == b'GIF89a':
                        image_format = "image/gif"
                    
                    print(f"Detected image format: {image_format}")
                    
                    image_analysis = analyze_image_with_claude(content_bytes, image_format)
                    print(f"Claude Vision analysis completed. Generated {len(image_analysis)} characters")
                    
                    if image_analysis.strip():
                        extracted_texts.append(f"Image analysis from {attachment['name']}: {image_analysis}")
                        print(f"✅ Successfully analyzed {attachment['name']}: {image_analysis[:100]}...")
                    else:
                        print(f"⚠️ No analysis generated for {attachment['name']}")
                    
            except Exception as e:
                print(f"❌ Error processing attachment {attachment.get('name', 'unknown')}: {e}")
        else:
            print(f"⏭️ Skipping non-image attachment: {attachment.get('name', 'unknown')}")
    
    
    # Process inline images from email body
    for i, inline_image in enumerate(inline_images):
        try:
            print(f"Processing inline image {i+1}: {inline_image['name']}")
            
            # Decode base64 image data
            content_bytes = base64.b64decode(inline_image['data'])
            print(f"Decoded {len(content_bytes)} bytes of inline image data")
            
            # Analyze with Claude Vision
            analysis = analyze_image_with_claude(content_bytes, inline_image['format'])
            
            if analysis and len(analysis.strip()) > 0:
                extracted_texts.append(analysis)
                print(f"✅ Successfully analyzed inline image {inline_image['name']}: {analysis[:100]}...")
            else:
                print(f"❌ No analysis generated for inline image {inline_image['name']}")
                
        except Exception as e:
            print(f"❌ Error processing inline image {inline_image['name']}: {e}")
    
    total_images = len([a for a in attachments if 'image' in a.get('contentType', '').lower()]) + len(inline_images)
    print(f"Attachment processing complete. Analyzed {len(extracted_texts)} images ({len(inline_images)} inline + attachments) with Claude Vision")
    return extracted_texts

def has_image_attachment(subject, body):
    """Detect if user mentions images/screenshots that we can't process"""
    text = f"{subject} {body}".lower()
    
    image_indicators = [
        'screenshot', 'image', 'picture', 'photo', 'attached', 'attachment',
        'see attached', 'see image', 'see screenshot', 'error message attached',
        'i attached', 'attached file', 'please see', 'as shown in'
    ]
    
    return any(indicator in text for indicator in image_indicators)

def generate_specific_questions(subject, description, sender_email):
    """Generate specific questions using Claude AI based on the issue type"""
    try:
        # Check if user attached images we can't see
        has_images = has_image_attachment(subject, description)
        
        image_note = ""
        if has_images:
            image_note = "\nIMPORTANT: The user has attached images/screenshots that our automated system cannot view. Make sure to ask for the exact text of any error messages shown in the images."
        
        # Use Claude to generate context-specific questions
        prompt = f"""You are an IT support specialist. A user has submitted this ticket:

Subject: {subject}
Description: {description}{image_note}

Generate a helpful response that includes:
1. 2-3 specific diagnostic questions to understand the problem better
2. 2-3 troubleshooting steps the user can try immediately

Format your response as bullet points starting with • for questions and ◦ for troubleshooting steps.

Focus on the specific technology, software, or hardware mentioned in the ticket.
Make the troubleshooting steps simple and safe for non-technical users.
IMPORTANT: Do not suggest "Run as administrator" or any admin-level actions as users do not have admin access.
{f"CRITICAL: If the user attached images/screenshots, you MUST ask them to type out the exact error message text since we cannot view images." if has_images else ""}

Example format:
• What specific error message appears when you try to open Excel?
• Does this happen with all Excel files or just specific ones?
◦ Try restarting Excel completely and opening a simple new workbook
◦ Check if Excel is up to date by going to File > Account > Update Options

Response:"""

        # Try the working model ID from claude-analyzer first
        model_ids = [
            'us.anthropic.claude-sonnet-4-20250514-v1:0',  # Working model from claude-analyzer
            'anthropic.claude-3-5-sonnet-20240620-v1:0',
            'anthropic.claude-3-haiku-20240307-v1:0'
        ]
        
        for model_id in model_ids:
            try:
                response = bedrock_client.invoke_model(
                    modelId=model_id,
                    body=json.dumps({
                        'anthropic_version': 'bedrock-2023-05-31',
                        'max_tokens': 300,
                        'messages': [
                            {
                                'role': 'user',
                                'content': prompt
                            }
                        ]
                    })
                )
                
                response_body = json.loads(response['body'].read())
                claude_questions = response_body['content'][0]['text'].strip()
                
                # Parse the questions and steps into a list
                items = []
                for line in claude_questions.split('\n'):
                    line = line.strip()
                    if line.startswith('•') or line.startswith('◦') or line.startswith('-'):
                        items.append(line)
                
                # If Claude returned good content, use it
                if len(items) >= 2:
                    print(f"Claude generated {len(items)} items using {model_id}")
                    if not has_contact_info(sender_email, description):
                        items.append("• Please provide your name and phone number for follow-up")
                    return items[:8]  # Limit to 8 items max
                    
            except Exception as e:
                print(f"Error with model {model_id}: {e}")
                continue
        
        # If all Claude models failed, use smart fallback based on subject
        print("All Claude models failed, using smart fallback")
        return generate_smart_fallback_questions(subject, description, sender_email)
        
    except Exception as e:
        print(f"Error generating Claude questions: {e}")
        return generate_smart_fallback_questions(subject, description, sender_email)

def generate_smart_fallback_questions(subject, description, sender_email):
    """Generate smart fallback questions based on keywords in the subject/description"""
    text = f"{subject} {description}".lower()
    
    # Excel/Office issues
    if any(word in text for word in ['excel', 'word', 'powerpoint', 'office', 'macro']):
        items = [
            "• What specific error message appears when you use the application?",
            "• Does this happen with all files or just specific ones?",
            "• Are you using Office 365, Office 2021, or an older version?",
            "◦ Try restarting the application completely",
            "◦ Check for Office updates: File > Account > Update Options",
            "◦ Try opening the application in Safe Mode (hold Ctrl while starting)"
        ]
    
    # Printer issues
    elif any(word in text for word in ['printer', 'print', 'printing']):
        items = [
            "• What specific error message appears when you try to print?",
            "• What printer model are you using?",
            "• Are you connected via USB, WiFi, or network cable?",
            "◦ Try restarting both your computer and the printer",
            "◦ Check if the printer appears in Settings > Printers & Scanners",
            "◦ Try printing a test page from the printer's control panel"
        ]
    
    # Email/Outlook issues
    elif any(word in text for word in ['email', 'outlook', 'mail']):
        items = [
            "• What specific error message do you see in Outlook?",
            "• Can you send emails, receive emails, or neither?",
            "• Are you working from home or in the office?",
            "◦ Try restarting Outlook completely",
            "◦ Check your internet connection",
            "◦ Try accessing email through the web browser (outlook.com)"
        ]
    
    # Generic fallback
    else:
        items = [
            "• What specific error messages do you see? (Please provide exact text)",
            "• What were you trying to do when this problem occurred?",
            "• When did this problem first start?",
            "◦ Try restarting the application or your computer",
            "◦ Check if there are any available updates for the software"
        ]
    
    if not has_contact_info(sender_email, description):
        items.append("• Please provide your name and phone number for follow-up")
    
    return items

def clean_search_query(query_text):
    """Clean and extract keywords from email for Confluence search"""
    # Remove ticket numbers and email formatting
    import re
    
    # Remove ticket numbers like [#CorpIT-28437]
    cleaned = re.sub(r'\[#[^\]]+\]', '', query_text)
    
    # Remove "New Ticket" prefix
    cleaned = re.sub(r'New Ticket[:\s]*', '', cleaned)
    
    # Remove email addresses and common email words
    cleaned = re.sub(r'\S+@\S+', '', cleaned)
    cleaned = re.sub(r'\b(from|to|subject|sent|received)\b', '', cleaned, flags=re.IGNORECASE)
    
    # Extract meaningful keywords (3+ characters)
    words = re.findall(r'\b[a-zA-Z]{3,}\b', cleaned)
    
    # Remove common stop words
    stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'man', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'its', 'let', 'put', 'say', 'she', 'too', 'use'}
    
    keywords = [word.lower() for word in words if word.lower() not in stop_words]
    
    # Return first 3-4 most relevant keywords
    return ' '.join(keywords[:4])

def generate_wiki_search_query(subject, body):
    """Use Claude to generate optimal wiki search terms from ticket"""
    try:
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        
        prompt = f"""Extract 3-5 key technical search terms from this IT support ticket for searching a wiki.

Ticket Subject: {subject}
Ticket Description: {body[:500]}

Return ONLY the search terms separated by spaces, nothing else. Focus on technical terms, product names, and issue types.

Examples:
- "My AWS workspace is slow" → "aws workspace slowness performance"
- "Can't access shared drive" → "shared drive access network"
- "Outlook not syncing emails" → "outlook email sync"

Search terms:"""

        response = bedrock.invoke_model(
            modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 50,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            })
        )
        
        result = json.loads(response['body'].read())
        search_terms = result['content'][0]['text'].strip()
        print(f"🔍 Claude generated search terms: {search_terms}")
        return search_terms
        
    except Exception as e:
        print(f"Error generating search query: {e}")
        # Fallback to basic cleaning
        clean_text = re.sub(r'<[^>]+>', '', f"{subject} {body}")
        return clean_text[:100]

def search_confluence_wiki(query_text):
    """Search Confluence for pages with foritchatbot label"""
    try:
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        # Clean the search query to extract keywords
        clean_query = clean_search_query(query_text)
        print(f"Original query: {query_text}")
        print(f"Cleaned query: {clean_query}")
        
        if not clean_query.strip():
            print("No meaningful keywords found in query")
            return None
        
        # Try title search first for better precision
        title_query = f'space = "IT" AND label = "foritchatbot" AND title ~ "{clean_query}"'
        print(f"Trying title search first: {title_query}")
        
        encoded_query = urllib.parse.quote(title_query)
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/search?cql={encoded_query}&limit=3"
        
        try:
            req = urllib.request.Request(search_url)
            req.add_header('Authorization', f'Basic {auth_b64}')
            req.add_header('Content-Type', 'application/json')
            
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    results = json.loads(response.read().decode('utf-8'))
                    if results.get('results') and len(results['results']) > 0:
                        print(f"Found {len(results['results'])} title matches")
                        best_match = results['results'][0]
                        page_id = best_match['content']['id']
                        page_content = get_page_content(page_id)
                        return {
                            'title': best_match['content']['title'],
                            'url': f"{CONFLUENCE_BASE_URL}/spaces/{CONFLUENCE_SPACE_KEY}/pages/{page_id}",
                            'content': page_content
                        }
        except Exception as e:
            print(f"Title search failed: {e}, falling back to content search")
        
        # Fall back to content search
        search_query = f'space = "IT" AND label = "foritchatbot" AND text ~ "{clean_query}"'
        
        # If query has multiple words, also try exact phrase search
        if len(clean_query.split()) > 1:
            exact_phrase_query = f'space = "IT" AND label = "foritchatbot" AND text ~ "\\"{clean_query}\\""'
            print(f"Trying exact phrase search: {exact_phrase_query}")
            
            # Try exact phrase first for better precision
            encoded_query = urllib.parse.quote(exact_phrase_query)
            search_url = f"{CONFLUENCE_BASE_URL}/rest/api/search?cql={encoded_query}&limit=3"
            
            try:
                req = urllib.request.Request(search_url)
                req.add_header('Authorization', f'Basic {auth_b64}')
                req.add_header('Content-Type', 'application/json')
                
                with urllib.request.urlopen(req) as response:
                    if response.status == 200:
                        results = json.loads(response.read().decode('utf-8'))
                        if results.get('results') and len(results['results']) > 0:
                            print(f"Found {len(results['results'])} exact phrase matches")
                            best_match = results['results'][0]
                            page_id = best_match['content']['id']
                            page_content = get_page_content(page_id)
                            return {
                                'title': best_match['content']['title'],
                                'url': f"{CONFLUENCE_BASE_URL}/spaces/{CONFLUENCE_SPACE_KEY}/pages/{page_id}",
                                'content': page_content
                            }
            except:
                print("Exact phrase search failed, falling back to word search")
        
        # Fall back to individual word search
        encoded_query = urllib.parse.quote(search_query)
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/search?cql={encoded_query}&limit=3"
        
        print(f"Confluence search query: {search_query}")
        print(f"Confluence search URL: {search_url}")
        
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                results = json.loads(response.read().decode('utf-8'))
                print(f"Confluence search results: {len(results.get('results', []))} found")
                if results.get('results') and len(results['results']) > 0:
                    best_match = results['results'][0]
                    page_id = best_match['content']['id']
                    page_content = get_page_content(page_id)
                    return {
                        'title': best_match['content']['title'],
                        'url': f"{CONFLUENCE_BASE_URL}/spaces/{CONFLUENCE_SPACE_KEY}/pages/{page_id}",
                        'content': page_content
                    }
                return None
    except urllib.error.HTTPError as e:
        print(f"HTTP Error searching Confluence: {e.code} - {e.reason}")
        if e.code == 400:
            print(f"Bad Request - Query may be malformed: {search_query}")
        return None
    except Exception as e:
        print(f"Error searching Confluence: {e}")
        return None

def get_page_content(page_id):
    """Get Confluence page content"""
    try:
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        content_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}?expand=body.storage"
        req = urllib.request.Request(content_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                page_data = json.loads(response.read().decode('utf-8'))
                html_content = page_data['body']['storage']['value']
                return html_to_text(html_content)
            else:
                return "Content not available"
    except Exception as e:
        print(f"Error getting page content: {e}")
        return "Content not available"

def html_to_text(html_content):
    """Convert HTML to clean plain text"""
    import re
    import html
    
    # First decode HTML entities
    clean_text = html.unescape(html_content)
    
    # Remove Confluence-specific markup and metadata
    clean_text = re.sub(r'<ac:structured-macro[^>]*>.*?</ac:structured-macro>', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'<ac:parameter[^>]*>.*?</ac:parameter>', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'<ac:rich-text-body>|</ac:rich-text-body>', '', clean_text)
    clean_text = re.sub(r'<ac:.*?>', '', clean_text)
    clean_text = re.sub(r'</ac:.*?>', '', clean_text)
    
    # Remove Confluence label queries and resource identifiers
    clean_text = re.sub(r'com\.atlassian\.confluence\.content\.render\.xhtml\.model\.resource\.identifiers\.[^\\s]*', '', clean_text)
    clean_text = re.sub(r'label\s*=\s*"[^"]*"\s*and\s*type\s*=\s*"[^"]*"\s*and\s*space\s*=\s*"[^"]*"', '', clean_text)
    clean_text = re.sub(r'false\d+[a-zA-Z]*', '', clean_text)
    
    # Convert basic HTML formatting
    clean_text = clean_text.replace('<br/>', '\n').replace('<br>', '\n').replace('</p>', '\n\n')
    clean_text = clean_text.replace('<h1>', '\n# ').replace('</h1>', '\n')
    clean_text = clean_text.replace('<h2>', '\n## ').replace('</h2>', '\n')
    clean_text = clean_text.replace('<h3>', '\n### ').replace('</h3>', '\n')
    clean_text = clean_text.replace('<strong>', '**').replace('</strong>', '**')
    clean_text = clean_text.replace('<em>', '*').replace('</em>', '*')
    
    # Remove all remaining HTML tags
    clean_text = re.sub(r'<[^>]+>', '', clean_text)
    
    # Clean up whitespace
    clean_text = re.sub(r'\n\s*\n\s*\n', '\n\n', clean_text)  # Multiple newlines to double
    clean_text = re.sub(r'[ \t]+', ' ', clean_text)  # Multiple spaces to single
    clean_text = re.sub(r'^\s+|\s+$', '', clean_text, flags=re.MULTILINE)  # Trim lines
    
    return clean_text.strip()

def send_email_response(access_token, to_email, subject, body, original_subject):
    """Send email response via Office 365 Graph API"""
    try:
        message = {
            'message': {
                'subject': f"Re: {original_subject}",
                'body': {
                    'contentType': 'Text',
                    'content': body
                },
                'toRecipients': [
                    {
                        'emailAddress': {
                            'address': to_email
                        }
                    }
                ]
            }
        }
        
        url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX_EMAIL}/sendMail"
        data = json.dumps(message).encode('utf-8')
        
        req = urllib.request.Request(url, data=data)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            if response.status == 202:
                print(f"Email sent successfully to {to_email}")
                return True
            else:
                print(f"Error sending email: {response.status}")
                return False
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def is_connection_slowness_issue(subject, body):
    """Detect if this is a connection SLOWNESS issue (not outages)"""
    text = f"{subject} {body}".lower()
    
    # Keywords that indicate SLOWNESS issues (not outages)
    slowness_keywords = [
        'slow', 'slowness', 'sluggish', 'lag', 'lagging', 'latency',
        'timeout', 'loading', 'buffering', 'frozen', 'freeze',
        'performance', 'speed', 'taking forever', 'takes long'
    ]
    
    # Connection types that can have slowness
    connection_types = [
        'workspace', 'aws workspace', 'vpn', 'connection', 'network'
    ]
    
    # Outage keywords that should NOT get the speed test response
    outage_keywords = [
        'down', 'offline', 'not working', 'broken', 'can\'t connect',
        'cannot connect', 'won\'t connect', 'disconnected', 'no connection',
        'error', 'failed', 'failure', 'unavailable'
    ]
    
    # Check if it's an outage issue first - if so, don't send speed test
    if any(outage in text for outage in outage_keywords):
        return False
    
    # Check if it has both slowness indicators AND connection types
    has_slowness = any(slowness in text for slowness in slowness_keywords)
    has_connection_type = any(conn_type in text for conn_type in connection_types)
    
    return has_slowness and has_connection_type

def is_hardware_request(subject, body):
    """Detect if this is a hardware request that should go directly to IT team"""
    text = f"{subject} {body}".lower()
    
    hardware_keywords = [
        'replace laptop',
        'new laptop', 
        'hardware request',
        'laptop swap',
        'needs a laptop',
        'needs a computer',
        'setup on a laptop',
        'setup on a computer',
        'setup on an',
        'new computer',
        'needs an ever.ag laptop',
        'needs an ever.ag computer',
        'laptop for',
        'computer for'
    ]
    
    return any(keyword in text for keyword in hardware_keywords)

def detect_issue_conflicts(subject, body):
    """Detect if multiple issue types are present in the ticket"""
    detected_issues = []
    
    # Check for various issue types
    if any(kw in f"{subject} {body}".lower() for kw in ['windows update', 'update fail', 'update error']):
        detected_issues.append('windows_update')
    
    if any(kw in f"{subject} {body}".lower() for kw in ['out of space', 'disk space', 'drive space', 'low space', 'disk full']):
        detected_issues.append('disk_space')
    
    if any(kw in f"{subject} {body}".lower() for kw in ['vpn', 'virtual private network']):
        detected_issues.append('vpn')
    
    if any(kw in f"{subject} {body}".lower() for kw in ['slow', 'slowness', 'performance', 'lag']):
        detected_issues.append('performance')
    
    if any(kw in f"{subject} {body}".lower() for kw in ['permission', 'access denied', 'cant access', "can't access"]):
        detected_issues.append('permissions')
    
    if any(kw in f"{subject} {body}".lower() for kw in ['shared mailbox', 'mailbox access']):
        detected_issues.append('shared_mailbox')
    
    return detected_issues

def analyze_primary_issue_with_claude(subject, body):
    """Use Claude to determine the primary issue when multiple issues are detected"""
    try:
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        
        prompt = f"""Analyze this IT support ticket and determine the PRIMARY issue that needs to be addressed.

Subject: {subject}
Body: {body}

Return ONLY ONE of these categories as the primary issue:
- disk_space (if the main problem is running out of storage/disk space)
- windows_update (if the main problem is about Windows update policy or manual updates)
- vpn (if the main problem is VPN connectivity)
- performance (if the main problem is slowness/lag)
- permissions (if the main problem is access/permission denied)
- shared_mailbox (if the main problem is shared mailbox access)
- hardware (if the main problem is hardware request/replacement)
- other (if none of the above)

Consider: What is the ROOT CAUSE that needs to be fixed? If updates are failing BECAUSE of disk space, the primary issue is disk_space, not windows_update.

Return only the category name, nothing else."""

        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 50,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            })
        )
        
        result = json.loads(response['body'].read())
        primary_issue = result['content'][0]['text'].strip().lower()
        
        print(f"🤖 Claude analysis - Primary issue: {primary_issue}")
        return primary_issue
        
    except Exception as e:
        print(f"Error in Claude analysis: {e}")
        return "other"

def extract_ticket_user_email(body, sender):
    """Extract actual user email from ticket body, fallback to sender"""
    # If sender is not itsupport, return it directly
    if 'itsupport@ever.ag' not in sender.lower():
        return sender
    
    # Try to extract from "Contact: Name" and convert to email
    contact_match = re.search(r'Contact:\s*([^<\n]+)', body, re.IGNORECASE)
    if contact_match:
        contact_name = contact_match.group(1).strip()
        # Remove any HTML tags that might have leaked through
        contact_name = re.sub(r'<[^>]+>', '', contact_name).strip()
        # Convert "First Last" to "first.last@ever.ag"
        email = contact_name.lower().replace(' ', '.') + '@ever.ag'
        print(f"📧 Extracted user email from Contact field: {email}")
        return email
    
    # Try to extract from "Name submitted a new help desk ticket"
    submitted_match = re.search(r'<strong>([^<]+)</strong>\s+submitted a new help desk ticket', body, re.IGNORECASE)
    if submitted_match:
        contact_name = submitted_match.group(1).strip()
        email = contact_name.lower().replace(' ', '.') + '@ever.ag'
        print(f"📧 Extracted user email from submission text: {email}")
        return email
    
    # Fallback to sender
    return sender

def is_workspaces_issue(subject, body):
    """Detect if this is an AWS WorkSpaces issue"""
    text = f"{subject} {body}".lower()
    
    workspaces_keywords = [
        'workspace', 'workspaces', 'aws workspace', 'virtual desktop',
        'remote desktop', 'workspace disconnect', 'workspace slow',
        'workspace not working', 'workspace error', 'workspace problem',
        'workspace issue', 'workspace crash', 'workspace freeze'
    ]
    
    return any(keyword in text for keyword in workspaces_keywords)

def get_user_workspace(user_email):
    """Find user's WorkSpace by email"""
    try:
        workspaces_client = boto3.client('workspaces', region_name='us-east-1')
        
        # Extract username from email (first.last@ever.ag -> first.last)
        username = user_email.split('@')[0] if '@' in user_email else user_email
        
        print(f"🔍 Looking for WorkSpace for user: {username}")
        
        # Search for WorkSpaces
        response = workspaces_client.describe_workspaces()
        
        for workspace in response.get('Workspaces', []):
            ws_username = workspace.get('UserName', '').lower()
            if username.lower() in ws_username or ws_username in username.lower():
                print(f"✅ Found WorkSpace: {workspace.get('WorkspaceId')}")
                return workspace
        
        print(f"❌ No WorkSpace found for {username}")
        return None
        
    except Exception as e:
        print(f"Error finding WorkSpace: {e}")
        return None

def check_workspace_health(workspace):
    """Check WorkSpace health and connection status"""
    try:
        workspaces_client = boto3.client('workspaces', region_name='us-east-1')
        
        workspace_id = workspace.get('WorkspaceId')
        
        # Get connection status
        conn_response = workspaces_client.describe_workspaces_connection_status(
            WorkspaceIds=[workspace_id]
        )
        
        conn_status = conn_response.get('WorkspacesConnectionStatus', [{}])[0]
        
        health_data = {
            'workspace_id': workspace_id,
            'username': workspace.get('UserName'),
            'state': workspace.get('State'),
            'compute_type': workspace.get('WorkspaceProperties', {}).get('ComputeTypeName'),
            'running_mode': workspace.get('WorkspaceProperties', {}).get('RunningMode'),
            'connection_state': conn_status.get('ConnectionState'),
            'last_known_connection': conn_status.get('LastKnownUserConnectionTimestamp'),
            'ip_address': workspace.get('IpAddress'),
            'error_code': workspace.get('ErrorCode'),
            'error_message': workspace.get('ErrorMessage')
        }
        
        print(f"📊 WorkSpace health data: {health_data}")
        return health_data
        
    except Exception as e:
        print(f"Error checking WorkSpace health: {e}")
        return None

def analyze_workspace_health_with_claude(health_data, issue_description):
    """Use Claude to analyze WorkSpace health and provide recommendations"""
    try:
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        
        prompt = f"""Analyze this AWS WorkSpace health data and provide a diagnosis and recommendations.

User's reported issue: {issue_description}

WorkSpace Health Data:
- WorkSpace ID: {health_data.get('workspace_id')}
- State: {health_data.get('state')}
- Connection State: {health_data.get('connection_state')}
- Last Connection: {health_data.get('last_known_connection')}
- Compute Type: {health_data.get('compute_type')}
- Running Mode: {health_data.get('running_mode')}
- Error Code: {health_data.get('error_code')}
- Error Message: {health_data.get('error_message')}

Provide:
1. Current Status (1-2 sentences)
2. Likely Cause (1-2 sentences)
3. Recommended Actions (2-3 bullet points)

Keep it concise and technical but understandable."""

        response = bedrock.invoke_model(
            modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 300,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            })
        )
        
        result = json.loads(response['body'].read())
        analysis = result['content'][0]['text'].strip()
        
        print(f"🤖 Claude WorkSpace analysis: {analysis}")
        return analysis
        
    except Exception as e:
        print(f"Error in Claude WorkSpace analysis: {e}")
        return "Unable to analyze WorkSpace health at this time."

def get_workspaces_diagnostic_response(health_data, analysis):
    """Generate diagnostic response for WorkSpaces issue"""
    return f"""**AWS WorkSpace Diagnostic:**

I've run a diagnostic check on your AWS WorkSpace and here's what I found:

**WorkSpace Information:**
• WorkSpace ID: {health_data.get('workspace_id')}
• Status: {health_data.get('state')}
• Connection State: {health_data.get('connection_state')}
• Compute Type: {health_data.get('compute_type')}

**Diagnostic Analysis:**
{analysis}

Our IT team has been notified and will investigate further if needed.

---
This diagnostic was automatically generated by 🤖 Brie IT Agent"""

def is_windows_update_issue(subject, body):
    """Detect if this is a Windows update issue that should be handled by IT (not user)"""
    text = f"{subject} {body}".lower()
    
    # Exclude if this is actually a disk space issue
    disk_space_keywords = [
        'out of space', 'disk space', 'drive space', 'storage space', 'low space',
        'no space', 'disk full', 'drive full', 'need more space', 'allocate space',
        'expand drive', 'extend volume', 'combine volume', 'merge volume',
        'c: drive', 'c drive', 'disk capacity', 'storage capacity'
    ]
    
    if any(keyword in text for keyword in disk_space_keywords):
        return False  # This is a disk space issue, not a Windows update issue
    
    update_keywords = [
        'windows update', 'windows updates', 'update fail', 'update error',
        'update not working', 'updates not installing', 'update problem',
        'kb update', 'security update', 'feature update', 'cumulative update',
        'i need updates', 'need them updates', 'failed updates', 'i see updates',
        'updates pending', 'updates available', 'update required', 'requires updates',
        'patch tuesday', 'windows patching', 'system updates'
    ]
    
    return any(keyword in text for keyword in update_keywords)

def get_windows_update_response():
    """Return the company-managed Windows update response"""
    return """Hello,

Thank you for reporting the Windows update issue.

Please note that all Windows updates are centrally managed through our patch management system. This means you won't be able to manually install updates, and the Windows Update screen on your laptop may not always display correctly since updates are being handled in the background by our system.

Our IT team will investigate and resolve this issue remotely to ensure your computer receives the appropriate updates through our managed process.

We'll also reach out to you shortly with any next steps.

---
This message was sent by our 🤖 Brie IT Agent"""

def is_specific_permission_request(subject, body):
    """Detect specific permission requests that should go directly to helpdesk"""
    text = f"{subject} {body}".lower()
    
    # EXCLUDE shared mailbox automation requests - let them go to it-action-processor
    shared_mailbox_keywords = ["shared mailbox", "shared mailboxes", "shared email"]
    access_keywords = ["grant", "give", "add", "access to", "permission", "provide access"]
    
    has_shared_mailbox = any(keyword in text for keyword in shared_mailbox_keywords)
    has_access_action = any(keyword in text for keyword in access_keywords)
    
    # If this looks like a shared mailbox automation request, don't send to helpdesk
    if has_shared_mailbox and has_access_action:
        return False
    
    # Indicators of specific permission requests
    permission_indicators = [
        "permission to",
        "permissions to", 
        "access to",
        "need access to",
        "could please have permission",
        "please give me access to",
        "i need permission for",
        "can i have access to"
    ]
    
    # Check if they're asking for permissions
    has_permission_request = any(indicator in text for indicator in permission_indicators)
    
    if not has_permission_request:
        return False
    
    # Look for specific named systems, projects, or detailed lists
    specific_indicators = [
        # They list specific items/projects
        len(re.findall(r'[A-Z][A-Z][A-Z]\s+[A-Za-z]+', body)) >= 2,  # "DAS Production", "DAS FieldAlytics" 
        # They mention having existing access but need more
        "i have an account" in text and ("do not have" in text or "need" in text),
        "already have access" in text and "need" in text,
        "able to access" in text and ("do not have" in text or "need" in text),
        # They list multiple specific items
        len(re.findall(r'-\s*[A-Za-z\s]+', body)) >= 3,  # Bulleted lists
    ]
    
    return any(specific_indicators)

def is_shared_mailbox_automation_request(subject, body):
    """Check if this is a shared mailbox request that should go to automation"""
    text = f"{subject} {body}".lower()
    
    # Check for shared mailbox keywords
    shared_mailbox_keywords = ["shared mailbox", "shared mailboxes", "shared email"]
    has_shared_mailbox = any(keyword in text for keyword in shared_mailbox_keywords)
    
    # Check for access action words
    access_keywords = ["grant", "give", "add", "access to", "permission", "provide access"]
    has_access_action = any(keyword in text for keyword in access_keywords)
    
    # Must have BOTH to be considered automation request
    return has_shared_mailbox and has_access_action

def is_access_provisioning_request(subject, body):
    """Detect access provisioning requests that need admin handling"""
    text = f"{subject} {body}".lower()
    
    provisioning_keywords = [
        "please allow access to",
        "grant access to", 
        "provide access to",
        "give access to",
        "requesting access for",
        "need access to @",
        "access to @",
        "allow access for"
    ]
    
    # SSO and system access patterns (specific systems)
    sso_access_patterns = [
        "access to everag sso",
        "access to sso",
        "sso access",
        "single sign-on access",
        "access to dynatrace",
        "access to orbis",
        "access to system",
        "system access",
        "application access"
    ]
    
    # Check for general provisioning keywords
    has_provisioning = any(keyword in text for keyword in provisioning_keywords)
    
    # Check for SSO/system access patterns (specific systems)
    has_specific_system_access = any(pattern in text for pattern in sso_access_patterns)
    
    return has_provisioning or has_specific_system_access

def is_complex_identity_issue(subject, body):
    """Detect complex identity/authentication issues that need immediate escalation"""
    text = f"{subject} {body}".lower()
    
    # Identity crisis indicators
    identity_patterns = [
        "changed my last name", "name change", "married name", "new last name",
        "changed my name", "name changed", "updated my name"
    ]
    
    # Authentication breakdown indicators
    auth_crisis_patterns = [
        "can't login to anything", "cannot login to anything", "can't access anything",
        "cannot access anything", "everything stopped working", "nothing works",
        "don't know my password", "lost my password", "password stored in",
        "locked out of everything", "can't get into anything"
    ]
    
    # Multi-system impact indicators
    multi_system_keywords = [
        "workday", "onepass", "teams", "outlook", "email", "microsoft", 
        "office", "sharepoint", "everything", "all systems", "all applications"
    ]
    
    # Urgency indicators
    urgency_patterns = [
        "asap", "urgent", "immediately", "right away", "can't work", 
        "need help now", "emergency", "critical"
    ]
    
    # Check for identity issues
    has_identity_issue = any(pattern in text for pattern in identity_patterns)
    
    # Check for authentication crisis
    has_auth_crisis = any(pattern in text for pattern in auth_crisis_patterns)
    
    # Count system mentions (multi-system impact)
    system_count = sum(1 for keyword in multi_system_keywords if keyword in text)
    has_multi_system = system_count >= 3
    
    # Check for urgency
    has_urgency = any(pattern in text for pattern in urgency_patterns)
    
    # Complex identity issue if:
    # (Identity change OR auth crisis) AND (multi-system OR urgency)
    return (has_identity_issue or has_auth_crisis) and (has_multi_system or has_urgency)

def is_secureframe_legitimacy_question(subject, body):
    """Detect questions about SecureFrame legitimacy/spam concerns"""
    text = f"{subject} {body}".lower()
    
    # SecureFrame mentions
    has_secureframe = "secureframe" in text
    
    # Legitimacy/spam concern indicators
    legitimacy_patterns = [
        "is this spam", "is this legit", "is this legitimate", "is this real",
        "need to make sure", "actually need to do", "is something i need",
        "spam or real", "legitimate email", "safe to", "should i trust"
    ]
    
    has_legitimacy_concern = any(pattern in text for pattern in legitimacy_patterns)
    
    return has_secureframe and has_legitimacy_concern

def is_mfa_enablement_request(subject, body):
    """Detect MFA enablement requests that should be sent to helpdesk silently"""
    text = f"{subject} {body}".lower()
    
    # MFA enablement patterns
    mfa_patterns = [
        "enable mfa", "enable multi-factor", "enable 2fa", "enable two-factor",
        "setup mfa", "set up mfa", "configure mfa", "turn on mfa",
        "activate mfa", "mfa setup", "multi-factor authentication"
    ]
    
    return any(pattern in text for pattern in mfa_patterns)

def is_emergency_change_notification(subject, body):
    """Detect emergency change notifications that should be sent to helpdesk silently"""
    text = f"{subject} {body}".lower()
    
    # Emergency change patterns
    emergency_change_patterns = [
        "emergency change has been submitted",
        "an emergency change has been",
        "emergency change notification",
        "emergency change request"
    ]
    
    return any(pattern in text for pattern in emergency_change_patterns)
    """Detect MFA enablement requests that should be sent to helpdesk silently"""
    text = f"{subject} {body}".lower()
    
    # MFA enablement patterns
    mfa_patterns = [
        "enable mfa", "enable multi-factor", "enable 2fa", "enable two-factor",
        "setup mfa", "set up mfa", "configure mfa", "turn on mfa",
        "activate mfa", "mfa setup", "multi-factor authentication"
    ]
    
    return any(pattern in text for pattern in mfa_patterns)
    """Detect questions about SecureFrame legitimacy/spam concerns"""
    text = f"{subject} {body}".lower()
    
    # SecureFrame mentions
    has_secureframe = "secureframe" in text
    
    # Legitimacy/spam concern indicators
    legitimacy_patterns = [
        "is this spam", "is this legit", "is this legitimate", "is this real",
        "need to make sure", "actually need to do", "is something i need",
        "spam or real", "legitimate email", "safe to", "should i trust"
    ]
    
    has_legitimacy_concern = any(pattern in text for pattern in legitimacy_patterns)
    
    return has_secureframe and has_legitimacy_concern
    """Detect complex identity/authentication issues that need immediate escalation"""
    text = f"{subject} {body}".lower()
    
    # Identity crisis indicators
    identity_patterns = [
        "changed my last name", "name change", "married name", "new last name",
        "changed my name", "name changed", "updated my name"
    ]
    
    # Authentication breakdown indicators
    auth_crisis_patterns = [
        "can't login to anything", "cannot login to anything", "can't access anything",
        "cannot access anything", "everything stopped working", "nothing works",
        "don't know my password", "lost my password", "password stored in",
        "locked out of everything", "can't get into anything"
    ]
    
    # Multi-system impact indicators
    multi_system_keywords = [
        "workday", "onepass", "teams", "outlook", "email", "microsoft", 
        "office", "sharepoint", "everything", "all systems", "all applications"
    ]
    
    # Urgency indicators
    urgency_patterns = [
        "asap", "urgent", "immediately", "right away", "can't work", 
        "need help now", "emergency", "critical"
    ]
    
    # Check for identity issues
    has_identity_issue = any(pattern in text for pattern in identity_patterns)
    
    # Check for authentication crisis
    has_auth_crisis = any(pattern in text for pattern in auth_crisis_patterns)
    
    # Count system mentions (multi-system impact)
    system_count = sum(1 for keyword in multi_system_keywords if keyword in text)
    has_multi_system = system_count >= 3
    
    # Check for urgency
    has_urgency = any(pattern in text for pattern in urgency_patterns)
    
    # Complex identity issue if:
    # (Identity change OR auth crisis) AND (multi-system OR urgency)
    return (has_identity_issue or has_auth_crisis) and (has_multi_system or has_urgency)
    """Check if access request has enough details to process"""
    text = f"{subject} {body}".lower()
    
    # Indicators of sufficient detail
    detail_indicators = [
        # Specific permissions/roles
        "read-only", "read only", "admin", "administrator", "full access", 
        "edit", "modify", "view", "viewer", "editor", "contributor",
        "permissions", "role", "rights", "privileges",
        
        # Business justification indicators
        "for monitoring", "for reporting", "for analysis", "for development",
        "for testing", "for support", "for maintenance", "for backup",
        "new employee", "replacement for", "same access as",
        
        # Specific technical details
        "service account", "api access", "database access", "file share",
        "distribution list", "security group", "active directory"
    ]
    
    # Check if request includes sufficient detail
    return any(indicator in text for indicator in detail_indicators)

def has_sufficient_access_details(subject, body):
    """Check if access request has enough details to process"""
    text = f"{subject} {body}".lower()
    
    # Indicators of sufficient detail
    detail_indicators = [
        # Specific permissions/roles
        "read-only", "read only", "admin", "administrator", "full access", 
        "edit", "modify", "view", "viewer", "editor", "contributor",
        "permissions", "role", "rights", "privileges",
        
        # Business justification indicators
        "for monitoring", "for reporting", "for analysis", "for development",
        "for testing", "for support", "for maintenance", "for backup",
        "new employee", "replacement for", "same access as",
        
        # Specific technical details
        "service account", "api access", "database access", "file share",
        "distribution list", "security group", "active directory"
    ]
    
    # Check if request includes sufficient detail
    return any(indicator in text for indicator in detail_indicators)

def is_vague_access_request(subject, body):
    """Detect access requests that need more information"""
    text = f"{subject} {body}".lower()
    
    # Access request patterns
    access_patterns = [
        "need access", "i need access", "requesting access", "access request",
        "can i get access", "access to", "give me access", "grant access"
    ]
    
    # Check if it's an access request
    has_access_request = any(pattern in text for pattern in access_patterns)
    
    # If it's an access request, check if it has sufficient details
    if has_access_request:
        return not has_sufficient_access_details(subject, body)
    
    return False

def is_internal_team_communication(subject, body, sender=None):
    """Detect internal team communications that need human handling"""
    text = f"{subject} {body}".lower()
    
    # FIRST: Check if this is a user ticket (not internal communication)
    user_ticket_indicators = [
        'submitted a new help desk ticket',
        'submitted a help desk ticket',
        'new help desk ticket',
        'ticket #:',
        'corpit-',
        'contact:',
        'status: open',
        'priority: medium',
        'priority: high',
        'priority: low'
    ]
    
    # If it's a user ticket, it's NOT internal communication
    for indicator in user_ticket_indicators:
        if indicator in text:
            print(f"✅ Found user ticket indicator: '{indicator}' - NOT internal communication")
            return False
    
    print(f"⚠️ No user ticket indicators found in text (first 200 chars): {text[:200]}")
    
    # EXCLUDE shared mailbox automation requests - let them go to it-action-processor
    shared_mailbox_keywords = ["shared mailbox", "shared mailboxes", "shared email"]
    access_keywords = ["grant", "give", "add", "access to", "permission", "provide access"]
    
    has_shared_mailbox = any(keyword in text for keyword in shared_mailbox_keywords)
    has_access_action = any(keyword in text for keyword in access_keywords)
    
    # If this looks like a shared mailbox automation request, don't classify as internal team communication
    if has_shared_mailbox and has_access_action:
        return False
    
    # Team communication indicators
    team_indicators = [
        'hi team', 'hey team', 'hello team', 'team,',
        'wanted to pass this along', 'wanted to pass along', 'fyi',
        'heads up', 'notification in devops', 'got this notification',
        'primarily controlled by', 'corp it team', 'it team',
        'devops', 'infrastructure', 'inter-team', 'internal team'
    ]
    
    # Administrative/infrastructure keywords
    admin_keywords = [
        'upcoming changes', 'firewall configuration', 'network allow lists',
        'what you need to do', 'action needed', 'configuration updates',
        'authentication process', 'endpoints'
    ]
    
    has_team_indicator = any(indicator in text for indicator in team_indicators)
    has_admin_keyword = any(keyword in text for keyword in admin_keywords)
    
    return has_team_indicator or has_admin_keyword

def is_microsoft_licensing_inquiry(subject, body):
    """Detect Microsoft licensing/subscription inquiries that need admin handling"""
    text = f"{subject} {body}".lower()
    
    licensing_keywords = [
        'teams premium trial', 'office 365 trial', 'microsoft 365 trial',
        'subscription expires', 'trial expires', 'trial ends',
        'licensing plan', 'license expires', 'subscription renewal',
        'teams premium access', 'office 365 license', 'microsoft 365 license',
        'trial information', 'subscription name', 'expiration date'
    ]
    
    # Must have Microsoft context + licensing terms
    has_microsoft = any(ms_term in text for ms_term in ['microsoft', 'office 365', 'microsoft 365', 'teams'])
    has_licensing = any(license_term in text for license_term in licensing_keywords)
    
    return has_microsoft and has_licensing

def is_ticket_status_inquiry(subject, body):
    """Detect ticket status inquiries that need human handling"""
    text = f"{subject} {body}".lower()
    
    # More specific phrases that clearly indicate status inquiries
    status_keywords = [
        'update on the below ticket', 'update on ticket #', 'update on ticket number',
        'status of ticket #', 'status of ticket number', 'status on ticket #',
        'waiting for completion of the ticket', 'waiting for the completion of ticket',
        'have not gotten an update on', 'haven\'t received an update on',
        'still waiting for completion', 'no update on ticket',
        'follow up on ticket #', 'follow up on ticket number',
        'checking on the status', 'checking status of ticket'
    ]
    
    return any(keyword in text for keyword in status_keywords)

def is_onboarding_offboarding_ticket(subject, body):
    """Detect onboarding/offboarding tickets that need human handling"""
    subject_lower = subject.lower()
    
    return 'onboarding' in subject_lower or 'offboarding' in subject_lower

def is_email_forwarding_request(subject, body):
    """Detect email forwarding/routing requests that need admin handling"""
    text = f"{subject} {body}".lower()
    
    forwarding_keywords = [
        'enable email address', 'enable the email address', 'enable old email',
        'email received routed', 'route email', 'forward email', 'email forwarding',
        'redirect email', 'email redirection', 'route to me', 'forward to me',
        'have all email', 'email routing', 'mailbox forwarding'
    ]
    
    return any(keyword in text for keyword in forwarding_keywords)

def is_international_travel_request(subject, body):
    """Detect international travel/access requests that need human handling"""
    text = f"{subject} {body}".lower()
    
    travel_keywords = [
        'planned travel', 'planning to travel', 'travel to', 'traveling to',
        'travelling to', 'going to travel', 'will be traveling', 'will be travelling',
        'international travel', 'overseas travel', 'outside the us', 'outside of the us'
    ]
    
    # Common international locations/regions
    international_locations = [
        'hong kong', 'china', 'japan', 'korea', 'singapore', 'india', 'australia',
        'uk', 'united kingdom', 'england', 'france', 'germany', 'italy', 'spain',
        'canada', 'mexico', 'brazil', 'argentina', 'europe', 'asia', 'africa'
    ]
    
    has_travel_keyword = any(keyword in text for keyword in travel_keywords)
    has_international_location = any(location in text for location in international_locations)
    
    return has_travel_keyword or has_international_location

def is_simple_information_request(subject, body):
    """Detect simple information requests that should go directly to helpdesk"""
    text = f"{subject} {body}".lower()
    
    # Simple information request patterns
    info_patterns = [
        "can someone tell me what",
        "what is my",
        "what's my", 
        "tell me what",
        "can you tell me",
        "what should my",
        "what dial pad",
        "what extension",
        "what phone number",
        "what is the",
        "can someone look up"
    ]
    
    return any(pattern in text for pattern in info_patterns)

def is_account_creation_request(subject, body):
    """Detect account creation/provisioning requests that need admin handling"""
    text = f"{subject} {body}".lower()
    
    creation_keywords = [
        'create account', 'create an account', 'new account', 'add user', 'add a user',
        'create email account', 'new email account', 'set up account', 'setup account',
        'provision', 'provisioning', 'create user', 'new user account',
        'add to system', 'create mailbox', 'new mailbox', 'user creation',
        'create email', 'create an email', 'set up email', 'setup email',
        'contractor email', 'contractor account', 'new contractor', 'create contractor'
    ]
    
    return any(keyword in text for keyword in creation_keywords)

def is_ever_ag_welcome_email(subject, body):
    """Detect specific Ever.Ag welcome email that needs portal move response"""
    subject_lower = subject.lower()
    body_lower = body.lower()
    
    # Check for specific subject and content
    has_action_required_subject = '[action required] welcome to ever.ag' in subject_lower
    has_welcome_content = 'welcome to ever.ag!' in body_lower
    has_password_change = 'before you can log in for the first time' in body_lower and 'click here to change your password' in body_lower
    
    return has_action_required_subject and has_welcome_content and has_password_change

def get_portal_move_response():
    """Return the portal move response for Ever.Ag welcome emails"""
    return """Hello,

This is a legitimate email related to a portal move. If you need more help on this please reach out to support@ever.ag Internal IT Support does not have details about this solution.

---
This message was sent by our 🤖 Brie IT Agent"""

def is_new_employee_welcome(subject, body):
    """Detect new employee welcome/onboarding emails"""
    text = f"{subject} {body}".lower()
    
    welcome_indicators = [
        'welcome to ever.ag',
        'welcome to ever ag',
        'action required] welcome',
        'before you can log in for the first time',
        'click here to change your password',
        'new employee',
        'first time login',
        'activate your account',
        'set up your password'
    ]
    
    return any(indicator in text for indicator in welcome_indicators)

def is_distribution_list_inquiry(subject, body):
    """Detect requests for distribution list/group membership information and modifications"""
    text = f"{subject} {body}".lower()
    
    # Keywords that indicate asking about group membership OR requesting modifications
    inquiry_phrases = [
        "who all receives emails",
        "who receives emails going to",
        "who gets emails to",
        "who is on the distribution list",
        "who is in the group",
        "list of recipients",
        "members of",
        "distribution list members",
        "group members",
        "email group members",
        # Add modification request keywords
        "add to the distribution list",
        "add to distribution list",
        "add the following to",
        "add people to",
        "add users to",
        "remove from the distribution list",
        "remove from distribution list",
        "remove people from",
        "remove users from",
        "can we please add",
        "please add to the list",
        "add to the local distribution"
    ]
    
    return any(phrase in text for phrase in inquiry_phrases)

def is_permission_question(subject, body):
    """Detect permission-related questions that need human review"""
    text = f"{subject} {body}".lower()
    
    permission_questions = [
        "has my permission changed",
        "has my admin permission changed",
        "have my permissions changed",
        "did my permissions change",
        "why don't i have permission",
        "why can't i access",
        "permission level changed",
        "access level changed",
        "my permissions were removed"
    ]
    
    return any(question in text for question in permission_questions)

def has_microsoft_access_denied(subject, body):
    """Detect Microsoft access denied errors that need helpdesk attention"""
    text = f"{subject} {body}".lower()
    
    # More specific access denied phrases - actual error messages only
    access_denied_phrases = [
        "you cannot access this right now",
        "your sign-in was successful but does not meet the criteria to access this resource",
        "does not meet the criteria to access this resource",
        "sign-in was successful but does not meet the criteria",
        "access denied",
        "forbidden error",
        "you don't have permission to access"
    ]
    
    # Check if it's Microsoft-related AND has actual access denied error message
    microsoft_keywords = ['microsoft', 'office 365', 'azure', 'outlook', 'teams', 'sharepoint', 'onedrive']
    
    has_microsoft = any(keyword in text for keyword in microsoft_keywords)
    has_access_denied = any(phrase in text for phrase in access_denied_phrases)
    
    return has_microsoft and has_access_denied

def is_daily_admin_task(subject, body):
    """Detect if this is a daily admin task that should just be deleted"""
    text = f"{subject} {body}".lower()
    return 'daily admin task' in text

def is_sso_group_request(subject, body):
    """Detect SSO group access requests that can be automated"""
    text = f"{subject} {body}".lower()
    
    # SSO Group keywords - match Slack bot logic
    if any(kw in text for kw in ['sso', 'active directory', 'ad group']):
        if any(action in text for action in ['add', 'remove', 'grant', 'revoke', 'access']):
            return True
    
    return False

def is_shared_mailbox_request(subject, body):
    """Detect shared mailbox access requests that can be automated"""
    text = f"{subject} {body}".lower()
    
    # Keywords that indicate shared mailbox requests
    mailbox_keywords = [
        "shared mailbox", "shared mail", "mailbox access", "access to shared",
        "grant access to", "add to mailbox", "mailbox permission", "shared email"
    ]
    
    has_mailbox_keywords = any(keyword in text for keyword in mailbox_keywords)
    
    if not has_mailbox_keywords:
        return False
    
    # Must have email addresses
    import re
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    has_emails = bool(re.findall(email_pattern, body, re.IGNORECASE))
    
    # Must have user names or clear request pattern
    user_patterns = [
        r'grant\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+access',
        r'add\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+to',
        r'give\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+access',
        r'([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+access\s+to',
        r'add\s+me\s+to.*@[a-z0-9.-]+\.[a-z]{2,}',  # "Add me to mailbox@domain"
        r'give\s+me\s+access.*@[a-z0-9.-]+\.[a-z]{2,}',  # "Give me access to mailbox@domain"
    ]
    has_user_patterns = any(re.search(pattern, body, re.IGNORECASE) for pattern in user_patterns)
    
    return has_mailbox_keywords and has_emails and has_user_patterns

def is_distribution_list_request(subject, body):
    """Detect distribution list access requests that can be automated"""
    text = f"{subject} {body}".lower()
    
    # Keywords that indicate distribution list requests
    distlist_keywords = [
        "outlook access",
        "email access", 
        "distribution list",
        "shared mailbox",
        "give access to",
        "add to",
        "access for the inbox",
        "access to inbox",
        "give her outlook access",
        "give him outlook access",
        "access for the inboxes",
        "setup forwarding email",
        "email forwarding",
        "forward email",
        "forwarding setup",
        "setup email forwarding"
    ]
    
    # Must have distribution list keywords
    has_distlist_keywords = any(keyword in text for keyword in distlist_keywords)
    
    # Must have email addresses
    import re
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    has_emails = bool(re.findall(email_pattern, body, re.IGNORECASE))
    
    # Must have user names (improved patterns)
    user_patterns = [
        r'([A-Z][a-z]+ [A-Z][a-z]+) will be',
        r'give ([A-Z][a-z]+ [A-Z][a-z]+) access',
        r'give ([A-Z][a-z]+ [A-Z][a-z]+) outlook',
        r'please give ([A-Z][a-z]+ [A-Z][a-z]+)',
        r'add ([A-Z][a-z]+ [A-Z][a-z]+) to',
        r'([A-Z][a-z]+ [A-Z][a-z]+) needs access',
        r'([A-Z][a-z]+ [A-Z][a-z]+) should have access'
    ]
    has_user_names = any(re.search(pattern, body, re.IGNORECASE) for pattern in user_patterns)
    
    return has_distlist_keywords and has_emails and has_user_names

def send_action_to_processor(access_token, subject, body, sender, message_id):
    """Send actionable request to IT Action Processor"""
    try:
        # Invoke IT Action Processor Lambda
        lambda_client = boto3.client('lambda')
        
        payload = {
            'action': 'analyze_request',
            'subject': subject,
            'body': body,
            'sender': sender,
            'message_id': message_id  # Pass message ID for email threading
        }
        
        response = lambda_client.invoke(
            FunctionName='it-action-processor',
            InvocationType='RequestResponse',  # Synchronous
            Payload=json.dumps(payload)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"📋 Action processor response: {result}")
        
        return result.get('statusCode') == 200
        
    except Exception as e:
        print(f"❌ Error sending to action processor: {e}")
        return False

def is_ticket_followup_request(subject, body):
    """Detect ticket follow-up requests that need immediate attention"""
    text = f"{subject} {body}".lower()
    
    followup_keywords = [
        "could we please get the ticket",
        "can we get ticket",
        "please get the ticket",
        "ticket has been outstanding",
        "been outstanding since",
        "blocking our ability",
        "needs to be handled",
        "please handle ticket",
        "ticket needs attention",
        "follow up on ticket",
        "status on ticket"
    ]
    
    # Must mention a ticket number (CorpIT-xxxxx format)
    has_ticket_reference = "corpit-" in text
    has_followup_language = any(keyword in text for keyword in followup_keywords)
    
    return has_ticket_reference and has_followup_language

def send_ticket_followup_to_slack(access_token, subject, body, sender):
    """Send ticket follow-up request to Slack channel via email"""
    slack_email = "ddc-global-infrastruc-aaaachje7gjhbglxbdrxrqq4sm@dairy.slack.com"
    
    alert_body = f"""TICKET FOLLOW-UP REQUEST: Urgent Attention Needed

Ticket Details:
Subject: {subject}
From: {sender}
Description: {body}

This appears to be a follow-up on an outstanding ticket that needs immediate attention.

This alert was automatically forwarded from the IT helpdesk system."""
    
    try:
        send_email_response(access_token, slack_email, f"URGENT: Ticket Follow-up - {subject}", alert_body, subject)
        print(f"Ticket follow-up alert sent to Slack: {subject}")
        return True
    except Exception as e:
        print(f"Error sending ticket follow-up alert to Slack: {e}")
        return False

def is_defender_security_threat(subject, body):
    """Detect Microsoft 365 Defender security threat alerts"""
    text = f"{subject} {body}".lower()
    
    defender_keywords = [
        "microsoft 365 defender has detected a security threat",
        "defender has detected a security threat",
        "microsoft defender has detected a security threat",
        "365 defender has detected a security threat"
    ]
    
    return any(keyword in text for keyword in defender_keywords)

def is_user_at_risk_alert(subject, body):
    """Detect if this is a 'User at risk detected' security alert"""
    text = f"{subject} {body}".lower()
    return 'user at risk detected' in text

def send_defender_alert_to_slack(access_token, subject, body, sender):
    """Send Defender security threat alert to Slack channel via email"""
    slack_email = "ddc-global-infrastruc-aaaachje7gjhbglxbdrxrqq4sm@dairy.slack.com"
    
    alert_body = f"""SECURITY ALERT: Microsoft 365 Defender Security Threat Detected

Ticket Details:
Subject: {subject}
From: {sender}
Description: {body}

This alert was automatically forwarded from the IT helpdesk system."""
    
    try:
        send_email_response(access_token, slack_email, f"SECURITY ALERT: Defender Threat - {subject}", alert_body, subject)
        print(f"Defender security alert sent to Slack: {subject}")
        return True
    except Exception as e:
        print(f"Error sending Defender alert to Slack: {e}")
        return False

def send_security_alert_to_slack(access_token, subject, body, sender):
    """Send security alert to Slack channel via email"""
    slack_email = "ddc-global-infrastruc-aaaachje7gjhbglxbdrxrqq4sm@dairy.slack.com"
    
    alert_body = f"""SECURITY ALERT: User at Risk Detected

Ticket Details:
Subject: {subject}
From: {sender}
Description: {body}

This is an automated security alert forwarded by Brie IT Agent.
Please investigate immediately.

---
Automated by 🤖 Brie IT Agent"""
    
    return send_email_response(access_token, slack_email, f"SECURITY ALERT: {subject}", alert_body, subject)

def is_automated_system_email(subject, body):
    """Detect if this email is from another bot/automated system that should be ignored"""
    text = f"{subject} {body}".lower()
    
    # Keywords that indicate automated systems/bots
    automated_keywords = [
        'bot troubleshooting suggestions provided',
        'it helpdesk slack bot',
        'automated response',
        'auto-generated',
        'system notification',
        'automated notification',
        'bot response',
        'slack bot'
    ]
    
    return any(keyword in text for keyword in automated_keywords)

def is_paid_software_request(subject, body):
    """Detect if this is a request for paid software that needs cost approval"""
    text = f"{subject} {body}".lower()
    
    # First check if this is a troubleshooting/access issue, not a purchase request
    troubleshooting_indicators = [
        "cannot access", "can't access", "unable to access", "cannot seem to access",
        "having trouble", "having issues", "not working", "doesn't work", "won't work",
        "error", "problem", "issue", "trouble accessing", "can't get to", "won't load",
        "not loading", "cannot open", "can't open", "unable to open", "not available"
    ]
    
    # If it's a troubleshooting issue, don't treat as paid software request
    if any(indicator in text for indicator in troubleshooting_indicators):
        return False
    
    # Paid software that requires approval
    paid_software = {
        'visio': {
            'cost': '$196.20',
            'name': 'Visio'
        },
        'acrobat pro': {
            'cost': '$285.48', 
            'name': 'Acrobat Pro'
        },
        'adobe pro': {
            'cost': '$285.48', 
            'name': 'Adobe Pro'
        },
        'acrobat standard': {
            'cost': '$173.28',
            'name': 'Acrobat Standard DC'
        },
        'copilot': {
            'cost': '$340.20',
            'name': 'Microsoft 365 Copilot'
        }
    }
    
    for software_key, software_info in paid_software.items():
        if software_key in text and any(keyword in text for keyword in ['need', 'request', 'access', 'license', 'subscription']):
            return software_info
    
    return None

def get_connection_issue_response():
    """Return the standardized connection issue response"""
    return """Hello,

We acknowledge the difficulties you're experiencing.

It's important to note that a robust and stable internet connection is crucial for accessing VPN and AWS servers. We kindly ask that you perform the following steps:

1. Open a web browser on your computer and mobile device (e.g., Chrome, Firefox, Safari).
2. In the address bar at the top of the browser, type 'www.speedtest.net' and press Enter.
3. Wait for the Speedtest.net homepage to load completely.
4. On the homepage, locate the large 'GO' button in the center of the screen.
5. Click the 'GO' button to begin the speed test.
6. The test will measure your download speed, upload speed, ping, and latency.
7. Wait for the test to complete. This usually takes less than a minute.
8. Once the test is finished, your results will be displayed on the screen.
9. Please screenshot the results on both your computer and mobile device and provide these to IT. (Reply All to the Genuity Ticket and attach screenshots to email)
10. Wait another hour and repeat steps 1 through 9, providing the screenshots to IT again.

We apologize for any inconvenience this may be causing. We will also review any logs or resources regarding your problem.

---
This message was sent by our 🤖 Brie IT Agent"""

def user_provided_good_troubleshooting(subject, body):
    """Check if user already provided good troubleshooting details"""
    text = f"{subject} {body}".lower()
    
    # Indicators that user already tried troubleshooting
    troubleshooting_indicators = [
        'i have tried', 'i tried', 'already tried', 'have tested', 'i tested',
        'plugged into', 'connected to', 'switched to', 'restarted', 'rebooted',
        'reinstalled', 'updated', 'checked', 'verified', 'attempted',
        'tested on another', 'tried another', 'different computer', 'other computer',
        'works on', 'working on', 'tried different', 'multiple', 'various'
    ]
    
    # Count how many troubleshooting indicators are present
    troubleshooting_count = sum(1 for indicator in troubleshooting_indicators if indicator in text)
    
    # If user mentioned 2+ troubleshooting steps, they provided good details
    return troubleshooting_count >= 2

def get_paid_software_response(software_info):
    """Return the cost approval response for paid software"""
    return f"""Hello,

The annual fee for {software_info['name']} is {software_info['cost']} US, and it comes with a one-year commitment. Approval from your Department Head or VP is necessary for this cost. Kindly update this ticket with their responses.

---
This message was sent by our 🤖 Brie IT Agent"""

def is_access_request(subject, body):
    """Detect if this is a general access request"""
    text = f"{subject} {body}".lower()
    
    # First check if it's a paid software request (these get responses)
    if is_paid_software_request(subject, body):
        return False  # Don't treat as general access request
    
    access_keywords = [
        'need access', 'access to', 'give me access', 'grant access',
        'permission to', 'permissions for', 'can i have access',
        'request access', 'access please', 'i need', 'need permission',
        'add me to', 'give me', 'can you give me', 'provide access'
    ]
    
    return any(keyword in text for keyword in access_keywords)

def is_specific_access_request(subject, body):
    """Check if access request includes specific details about what they need"""
    text = f"{subject} {body}".lower()
    
    # Specific systems/applications they might request access to
    specific_targets = [
        'sharepoint', 'onedrive', 'teams', 'outlook', 'exchange', 'active directory',
        'salesforce', 'jira', 'confluence', 'aws', 'azure', 'office 365',
        'folder', 'drive', 'database', 'server', 'application', 'system',
        'network', 'vpn', 'printer', 'shared drive', 'file share', 'onepassword', '1password'
    ]
    
    # Check if they mention what they need access to
    has_specific_target = any(target in text for target in specific_targets)
    
    # Check if they provide context (why they need it, what for)
    context_indicators = [
        'for my job', 'for work', 'to do my', 'because', 'so i can', 'in order to',
        'need it for', 'required for', 'project', 'department', 'team', 'role'
    ]
    has_context = any(indicator in text for indicator in context_indicators)
    
    return has_specific_target or has_context

def get_access_request_questions():
    """Return questions for vague access requests"""
    return """Hello,

Thank you for contacting IT support. To help us process your access request quickly, please provide the following information:

• What specific system, application, or resource do you need access to? (e.g., SharePoint site, shared folder, application name)
• What is your business justification for needing this access? (e.g., job role requirements, specific project needs)
• Do you need the same level of access as a specific colleague, or do you know what permissions you require?
• Is this access needed immediately, or do you have a specific deadline?
• Has your manager or department head approved this access request?

The more specific details you provide, the faster we can process your request.

---
This message was sent by our 🤖 Brie IT Agent"""

def user_provided_good_troubleshooting(subject, body):
    """Check if user already provided good troubleshooting details"""
    text = f"{subject} {body}".lower()
    
    # Indicators that user already tried troubleshooting
    troubleshooting_indicators = [
        'i have tried', 'i tried', 'already tried', 'have tested', 'i tested',
        'attempted to', 'have attempted', 'tried to', 'have done', 'i did',
        'already done', 'have checked', 'checked', 'verified', 'confirmed',
        'restarted', 'rebooted', 'reset', 'cleared cache', 'cleared cookies',
        'uninstalled', 'reinstalled', 'updated', 'upgraded', 'downgraded',
        'different browser', 'another browser', 'incognito', 'private mode',
        'safe mode', 'administrator', 'admin mode', 'compatibility mode',
        'troubleshoot', 'diagnostic', 'scan', 'repair', 'fix', 'resolve',
        'plugged into', 'connected to', 'switched to', 'restarted', 'rebooted',
        'reinstalled', 'updated', 'checked', 'verified', 'attempted',
        'tested on another', 'tried another', 'different computer', 'other computer',
        'works on', 'working on', 'tried different', 'multiple', 'various'
    ]
    
    # Count how many troubleshooting indicators are present
    troubleshooting_count = sum(1 for indicator in troubleshooting_indicators if indicator in text)
    
    # If user mentioned 2+ troubleshooting steps, they provided good details
    return troubleshooting_count >= 2
    """Return the standardized connection issue response"""
    return """Hello,

We acknowledge the difficulties you're experiencing.

It's important to note that a robust and stable internet connection is crucial for accessing VPN and AWS servers. We kindly ask that you perform the following steps:

1. Open a web browser on your computer and mobile device (e.g., Chrome, Firefox, Safari).
2. In the address bar at the top of the browser, type 'www.speedtest.net' and press Enter.
3. Wait for the Speedtest.net homepage to load completely.
4. On the homepage, locate the large 'GO' button in the center of the screen.
5. Click the 'GO' button to begin the speed test.
6. The test will measure your download speed, upload speed, ping, and latency.
7. Wait for the test to complete. This usually takes less than a minute.
8. Once the test is finished, your results will be displayed on the screen.
9. Please screenshot the results on both your computer and mobile device and provide these to IT. (Reply All to the Genuity Ticket and attach screenshots to email)
10. Wait another hour and repeat steps 1 through 9, providing the screenshots to IT again.

We apologize for any inconvenience this may be causing. We will also review any logs or resources regarding your problem.

---
This message was sent by our 🤖 Brie IT Agent"""

def process_email(access_token, email):
    """Process email with connection issue detection first"""
    try:
        sender = email['from']['emailAddress']['address']
        subject = email['subject']
        body = email['body']['content'] if email['body']['content'] else email['bodyPreview']
        message_id = email['id']
        
        print(f"Processing email from {sender}: {subject}")
        
        # Extract analysis from image attachments and inline images using Claude Vision
        attachment_analyses = process_email_attachments(access_token, message_id, body)
        attachments_info = []
        if attachment_analyses:
            # Add extracted analysis to the body for processing
            body += "\n\nImage analysis from attachments:\n" + "\n".join(attachment_analyses)
            print(f"Added Claude Vision analysis from {len(attachment_analyses)} image(s)")
            attachments_info = [f"Claude Vision analysis from {len(attachment_analyses)} images"]
        
        # STEP -1: Check if this is from another bot/automated system FIRST
        if is_automated_system_email(subject, body):
            print("Detected automated system email (bot-generated ticket) - deleting")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -1: Automated System", 
                               "Detected automated system email from IT Helpdesk Slack Bot", "Deleted - bot-generated ticket", 
                               None, attachments_info)
            return
        
        # STEP -1.0: Check if this is Ever.Ag welcome email (portal move)
        if is_ever_ag_welcome_email(subject, body):
            print("Detected Ever.Ag welcome email - sending portal move response")
            
            portal_response = get_portal_move_response()
            
            # TEMPORARY: Send to Matt for testing instead of original sender
            test_subject = f"[BRIE TEST] Portal Move Info for: {subject} (from {sender})"
            
            if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, portal_response, subject):
                delete_email(access_token, message_id)
                print("Portal move response sent to Matt for testing and email deleted")
                log_email_processing(message_id, sender, subject, body, "STEP -1.0: Ever.Ag Welcome", 
                                   "Portal move response", "Responded and deleted", 
                                   portal_response, attachments_info)
                return
        
        # STEP -0.95: Check if this is a new employee welcome email
        if is_new_employee_welcome(subject, body):
            print("Detected new employee welcome email - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.95: New Employee Welcome", 
                               "New employee welcome detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.9: Check if this is a distribution list inquiry
        if is_distribution_list_inquiry(subject, body):
            print("Detected distribution list inquiry - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.9: Distribution List", 
                               "Distribution list inquiry detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.75: Check if this is a permission question
        if is_permission_question(subject, body):
            print("Detected permission question - providing troubleshooting steps and routing to helpdesk")
            
            # Generate Claude response with troubleshooting steps
            claude_response = get_claude_response(subject, body, sender)
            
            # Add permission message at the top, then Claude response
            full_response = f"""Hello,

I can help with a few technical troubleshooting steps, but I'll leave your permissions-related question and the rest for a live help desk agent.

{claude_response}

---
This message was sent by our 🤖 Brie IT Agent"""
            
            send_email_response(access_token, sender, subject, full_response, subject)
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.75: Permission Question", 
                               claude_response, "Responded with troubleshooting and deleted", 
                               full_response, attachments_info)
            return
        
        # STEP -0.8: Check if this is Microsoft access denied error
        if has_microsoft_access_denied(subject, body):
            print("Detected Microsoft access denied error - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.8: Microsoft Access Denied", 
                               "Microsoft access denied error detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.7: Check if this is a daily admin task
        if is_daily_admin_task(subject, body):
            print("Detected daily admin task - deleting without response")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.7: Daily Admin Task", 
                               "Daily admin task detected", "Deleted - no response", 
                               None, attachments_info)
            return
        
        # STEP -0.683: Check if this is an emergency change notification
        if is_emergency_change_notification(subject, body):
            print("Detected emergency change notification - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.683: Emergency Change Notification", 
                               "Emergency change notification detected", "Sent to helpdesk - no response", 
                               None, attachments_info)
            return
        
        # STEP -0.684: Check if this is an MFA enablement request
        if is_mfa_enablement_request(subject, body):
            print("Detected MFA enablement request - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.684: MFA Enablement Request", 
                               "MFA enablement request detected", "Sent to helpdesk - no response", 
                               None, attachments_info)
            return
        
        # STEP -0.685: Check if this is a SecureFrame legitimacy question
        if is_secureframe_legitimacy_question(subject, body):
            print("Detected SecureFrame legitimacy question - providing confirmation")
            
            secureframe_response = """Hello,

SecureFrame is a legitimate system used by our organization for security compliance and task management. If you received an email from SecureFrame asking you to complete tasks, it is authentic and you should follow the instructions provided.

If you want more details about SecureFrame or have specific questions about the tasks, please contact security@ever.ag

---
This message was sent by our 🤖 Brie IT Agent"""
            
            send_email_response(access_token, sender, subject, secureframe_response, subject)
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.685: SecureFrame Legitimacy", 
                               "SecureFrame legitimacy question detected", "Responded with confirmation and deleted", 
                               secureframe_response, attachments_info)
            return
        
        # STEP -0.69: Check if this is a complex identity/authentication issue
        if is_complex_identity_issue(subject, body):
            print("Detected complex identity issue - escalating to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.69: Complex Identity Issue", 
                               "Complex identity/authentication issue detected", "Escalated to helpdesk - no response", 
                               None, attachments_info)
            return
        
        # STEP -0.675: Check if this is a vague access request that needs more info
        if is_vague_access_request(subject, body):
            print("Detected vague access request - asking for more details")
            
            vague_access_response = """I can help route your access request to the right team. Could you please specify:
• Which system or application you need access to
• Any specific permissions or roles needed

This will help us process your request more efficiently.

---
This message was sent by our 🤖 Brie IT Agent"""
            
            send_email_response(access_token, sender, subject, vague_access_response, subject)
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.675: Vague Access Request", 
                               "Vague access request detected", "Responded asking for details and deleted", 
                               vague_access_response, attachments_info)
            return
        
        # STEP -0.68: Check if this is an access provisioning request
        if is_access_provisioning_request(subject, body):
            print("Detected access provisioning request - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.68: Access Provisioning", 
                               "Access provisioning request detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.679: Check if this is a simple information request
        if is_simple_information_request(subject, body):
            print("Detected simple information request - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.679: Simple Information Request", 
                               "Simple information lookup request detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.678: Check if this is a termination ticket
        if 'termination' in subject.lower():
            print("Detected termination ticket - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.678: Termination Ticket", 
                               "Termination ticket detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.677: Check if this is a specific permission request with details
        if is_specific_permission_request(subject, body):
            print("Detected specific permission request with details - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.677: Specific Permission Request", 
                               "Specific permission request with sufficient details detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.676: Check if this is a ticket-based distribution list request
        if sender == "itsupport@ever.ag" and ("add" in subject.lower() and ("dl" in subject.lower() or "dl" in body.lower())) and not is_shared_mailbox_request(subject, body):
            print(f"Detected ticket-based distribution list request - Subject: '{subject}', Body contains DL: {'dl' in body.lower()}")
            
            if send_action_to_processor(access_token, subject, body, sender, message_id):
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP -0.676: Ticket Distribution List Request", 
                                   "Ticket-based distribution list request detected", "Sent to action processor and deleted", 
                                   None, attachments_info)
                print("Ticket distribution list request sent to action processor and email deleted")
                return
            else:
                print("Failed to send to action processor - falling back to normal processing")
        
        # STEP -0.675: Check if this is a ticket-based shared mailbox request
        if sender == "itsupport@ever.ag" and is_shared_mailbox_automation_request(subject, body):
            print(f"Detected ticket-based shared mailbox request - Subject: '{subject}'")
            
            if send_action_to_processor(access_token, subject, body, sender, message_id):
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP -0.675: Ticket Shared Mailbox Request", 
                                   "Ticket-based shared mailbox request detected", "Sent to action processor and deleted", 
                                   None, attachments_info)
                print("Ticket shared mailbox request sent to action processor and email deleted")
                return
            else:
                print("Failed to send shared mailbox request to action processor - falling back to normal processing")
        
        # STEP -0.674: Check if this is an SSO group request that can be automated
        if sender == "itsupport@ever.ag" and is_sso_group_request(subject, body):
            print("Detected SSO group request - sending to action processor")
            
            if send_action_to_processor(access_token, subject, body, sender, message_id):
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP -0.674: SSO Group Request", 
                                   "SSO group access request detected", "Sent to action processor and deleted", 
                                   None, attachments_info)
                print("SSO group request sent to action processor and email deleted")
                return
            else:
                print("Failed to send SSO group request to action processor - falling back to normal processing")
        
        # STEP -0.675.5: Check if this is a shared mailbox request that can be automated
        if sender == "itsupport@ever.ag" and is_shared_mailbox_request(subject, body):
            print("Detected shared mailbox request - sending to action processor")
            
            if send_action_to_processor(access_token, subject, body, sender, message_id):
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP -0.675.5: Shared Mailbox Request", 
                                   "Shared mailbox access request detected", "Sent to action processor and deleted", 
                                   None, attachments_info)
                print("Shared mailbox request sent to action processor and email deleted")
                return
            else:
                print("Failed to send to action processor - falling back to normal processing")
        
        # STEP -0.675: Check if this is a distribution list request that can be automated
        if is_distribution_list_request(subject, body):
            print("Detected distribution list request - sending to action processor")
            
            if send_action_to_processor(access_token, subject, body, sender, message_id):
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP -0.675: Distribution List Request", 
                                   "Distribution list access request detected", "Sent to action processor and deleted", 
                                   None, attachments_info)
                print("Distribution list request sent to action processor and email deleted")
                return
            else:
                print("Failed to send to action processor - falling back to normal processing")
        
        # STEP -0.67: Check if this is internal team communication
        if is_internal_team_communication(subject, body, sender):
            print("Detected internal team communication - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.67: Internal Team Communication", 
                               "Internal team communication detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.66: Check if this is a Microsoft licensing/subscription inquiry
        if is_microsoft_licensing_inquiry(subject, body):
            print("Detected Microsoft licensing inquiry - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.66: Microsoft Licensing", 
                               "Microsoft licensing inquiry detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.65: Check if this is a ticket status inquiry
        if is_ticket_status_inquiry(subject, body):
            print("Detected ticket status inquiry - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.65: Ticket Status Inquiry", 
                               "Ticket status inquiry detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.64: Check if this is an onboarding/offboarding ticket
        if is_onboarding_offboarding_ticket(subject, body):
            print("Detected onboarding/offboarding ticket - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.64: Onboarding/Offboarding", 
                               "Onboarding/offboarding ticket detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.63: Check if this is an email forwarding request
        if is_email_forwarding_request(subject, body):
            print("Detected email forwarding request - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.63: Email Forwarding", 
                               "Email forwarding request detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.62: Check if this is an international travel request
        if is_international_travel_request(subject, body):
            print("Detected international travel request - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.62: International Travel", 
                               "International travel request detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.6: Check if this is an account creation/provisioning request
        if is_account_creation_request(subject, body):
            print("Detected account creation request - sending to helpdesk (delete, no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.6: Account Creation", 
                               "Account creation request detected", "Deleted - sent to helpdesk", 
                               None, attachments_info)
            return
        
        # STEP -0.56: Check if this is a ticket follow-up request
        if is_ticket_followup_request(subject, body):
            print("Detected ticket follow-up request - forwarding to Slack and deleting")
            send_ticket_followup_to_slack(access_token, subject, body, sender)
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.56: Ticket Follow-up", 
                               "Ticket follow-up request detected", "Forwarded to Slack and deleted", 
                               None, attachments_info)
            return
        
        # STEP -0.55: Check if this is a Defender security threat alert
        if is_defender_security_threat(subject, body):
            print("Detected Microsoft 365 Defender security threat - forwarding to Slack and deleting")
            send_defender_alert_to_slack(access_token, subject, body, sender)
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.55: Defender Security Threat", 
                               "Microsoft 365 Defender security threat detected", "Forwarded to Slack and deleted", 
                               None, attachments_info)
            return
        
        # STEP -0.5: Check if this is a security alert that needs forwarding
        if is_user_at_risk_alert(subject, body):
            print("Detected 'User at risk' security alert - forwarding to Slack and deleting")
            send_security_alert_to_slack(access_token, subject, body, sender)
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP -0.5: User at Risk Alert", 
                               "User at risk security alert detected", "Forwarded to Slack and deleted", 
                               None, attachments_info)
            return
        
        # STEP 0: Check for conflicting issues and use Claude if needed
        detected_issues = detect_issue_conflicts(subject, body)
        
        if len(detected_issues) > 1:
            print(f"⚠️ Multiple issues detected: {detected_issues} - using Claude for analysis")
            primary_issue = analyze_primary_issue_with_claude(subject, body)
            
            # Skip Windows update response if primary issue is something else
            if primary_issue == 'disk_space':
                print("Primary issue is disk space - skipping Windows update response")
                # Continue to next checks
            elif primary_issue == 'windows_update':
                print("Primary issue confirmed as Windows update - sending response")
                update_response = get_windows_update_response()
                test_subject = f"[BRIE TEST] Windows Update - Company Managed for: {subject} (from {sender})"
                
                if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, update_response, subject):
                    delete_email(access_token, message_id)
                    print("Windows update response sent to Matt for testing and email deleted")
                    log_email_processing(message_id, sender, subject, body, "STEP 0: Windows Update Issue", 
                                       "Windows update issue detected", "Responded with company-managed info and deleted", 
                                       update_response, attachments_info)
                    return
        elif 'windows_update' in detected_issues:
            # Single issue detected - use simple check
            if is_windows_update_issue(subject, body):
                print("Detected Windows update issue - sending company-managed response")
                
                update_response = get_windows_update_response()
                test_subject = f"[BRIE TEST] Windows Update - Company Managed for: {subject} (from {sender})"
                
                if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, update_response, subject):
                    delete_email(access_token, message_id)
                    print("Windows update response sent to Matt for testing and email deleted")
                    log_email_processing(message_id, sender, subject, body, "STEP 0: Windows Update Issue", 
                                       "Windows update issue detected", "Responded with company-managed info and deleted", 
                                       update_response, attachments_info)
                    return
        
        # STEP 0B: Check if this is a hardware request
        if is_hardware_request(subject, body):
            print("Detected hardware request - sending directly to IT team (no response)")
            delete_email(access_token, message_id)
            log_email_processing(message_id, sender, subject, body, "STEP 0B: Hardware Request", 
                               "Hardware request detected", "Deleted - sent to IT team", 
                               None, attachments_info)
            return
        
        # STEP 0C: Check if this is a PAID SOFTWARE request FIRST
        paid_software = is_paid_software_request(subject, body)
        if paid_software:
            print(f"Detected paid software request: {paid_software['name']} - sending cost approval response")
            
            cost_response = get_paid_software_response(paid_software)
            
            # TEMPORARY: Send to Matt for testing instead of original sender
            test_subject = f"[BRIE TEST] Cost Approval for: {subject} (from {sender})"
            
            if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, cost_response, subject):
                delete_email(access_token, message_id)
                print("Cost approval response sent to Matt for testing and email deleted")
                log_email_processing(message_id, sender, subject, body, "STEP 0B: Paid Software Request", 
                                   f"Paid software request detected: {paid_software['name']}", "Responded with cost approval and deleted", 
                                   cost_response, attachments_info)
                return
        
        # STEP 0B: Check if this is a general access request
        if is_access_request(subject, body):
            if is_specific_access_request(subject, body):
                print("Detected specific access request - sending to helpdesk (delete, no response)")
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP 0B: Specific Access Request", 
                                   "Specific access request detected", "Deleted - sent to helpdesk", 
                                   None, attachments_info)
                return
            else:
                print("Detected vague access request - asking for more details")
                
                access_questions = get_access_request_questions()
                
                # TEMPORARY: Send to Matt for testing instead of original sender
                test_subject = f"[BRIE TEST] Access Request Details Needed for: {subject} (from {sender})"
                
                if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, access_questions, subject):
                    delete_email(access_token, message_id)
                    print("Access request questions sent to Matt for testing and email deleted")
                    log_email_processing(message_id, sender, subject, body, "STEP 0B: Vague Access Request", 
                                       "Vague access request detected", "Responded with questions and deleted", 
                                       access_questions, attachments_info)
                    return
        
        # STEP 1: Check if this is a connection SLOWNESS issue FIRST
        if is_connection_slowness_issue(subject, body):
            print("Detected connection slowness issue - sending standardized response")
            
            connection_response = get_connection_issue_response()
            
            # TEMPORARY: Send to Matt for testing instead of original sender
            test_subject = f"[BRIE TEST] Connection Issue Response for: {subject} (from {sender})"
            
            if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, connection_response, subject):
                delete_email(access_token, message_id)
                print("Connection slowness response sent to Matt for testing and email deleted")
                log_email_processing(message_id, sender, subject, body, "STEP 1: Connection Slowness", 
                                   "Connection slowness issue detected", "Responded with troubleshooting and deleted", 
                                   connection_response, attachments_info)
                return
        
        print("Not a connection slowness issue - using original wiki search logic")
        
        # STEP 1.5: Check if this is a WorkSpaces issue and gather diagnostic data
        workspace_diagnostic = None
        if is_workspaces_issue(subject, body):
            print("Detected AWS WorkSpaces issue - gathering diagnostic data")
            
            # Extract actual user email from ticket
            user_email = extract_ticket_user_email(body, sender)
            workspace = get_user_workspace(user_email)
            
            if workspace:
                health_data = check_workspace_health(workspace)
                if health_data:
                    issue_description = f"{subject}\n{body}"
                    analysis = analyze_workspace_health_with_claude(health_data, issue_description)
                    workspace_diagnostic = get_workspaces_diagnostic_response(health_data, analysis)
                    print(f"✅ WorkSpace diagnostic gathered for inclusion in response")
        
        # STEP 2: Original logic for non-connection issues
        search_query = generate_wiki_search_query(subject, body)
        wiki_result = search_confluence_wiki(search_query)
        
        if wiki_result:
            print(f"Found wiki solution: {wiki_result['title']}")
            
            if user_already_tried_wiki_steps(body, wiki_result['content']):
                print("User already tried wiki steps - just deleting for IT team")
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP 2: Wiki Found - User Tried", 
                                   f"Wiki solution found but user already tried steps: {wiki_result['title']}", "Deleted - sent to IT team", 
                                   None, attachments_info)
            else:
                print("Sending wiki solution to user")
                
                # Build solution body with optional WorkSpaces diagnostic
                solution_body = f"""Hello,

I found a solution that may help with your issue:

**{wiki_result['title']}**

{wiki_result['content']}

For more details, you can view the full article here: {wiki_result['url']}"""

                # Add WorkSpaces diagnostic if available
                if workspace_diagnostic:
                    solution_body += f"\n\n---\n\n{workspace_diagnostic}"
                
                solution_body += """

If this doesn't resolve your issue, please reply and a member of our IT team will assist you further.

---
This message was sent by our 🤖 Brie IT Agent"""

                # TEMPORARY: Send to Matt for testing instead of original sender
                test_subject = f"[BRIE TEST] Wiki Solution for: {subject} (from {sender})"
                
                if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, solution_body, subject):
                    delete_email(access_token, message_id)
                    log_email_processing(message_id, sender, subject, body, "STEP 2: Wiki Solution Sent", 
                                       f"Wiki solution found and sent: {wiki_result['title']}", "Responded with wiki solution and deleted", 
                                       solution_body, attachments_info)
        
        else:
            print("No wiki solution found - checking if user provided good troubleshooting")
            
            # Check if user already provided good troubleshooting details
            if user_provided_good_troubleshooting(subject, body):
                print("User provided good troubleshooting details - sending to IT team")
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP 3: Good Troubleshooting Provided", 
                                   "No wiki solution found but user provided good troubleshooting", "Deleted - sent to IT team", 
                                   None, attachments_info)
                return
            
            # Only use Claude if user didn't provide good troubleshooting
            if not is_ticket_detailed_enough(subject, body, sender):
                print("Claude says insufficient - asking for more details")
                
                specific_questions = generate_specific_questions(subject, body, sender)
                questions_text = "\n".join(specific_questions)
                
                # Check if we have troubleshooting steps (◦ items)
                has_troubleshooting = any(item.startswith('◦') for item in specific_questions)
                
                if has_troubleshooting:
                    intro_text = "To help us resolve your issue quickly, please provide the following information and try these troubleshooting steps:"
                else:
                    intro_text = "To help us resolve your issue quickly, please provide the following information:"
                
                more_details_body = f"""Hello,

Thank you for contacting IT support. {intro_text}

{questions_text}"""

                # Add WorkSpaces diagnostic if available
                if workspace_diagnostic:
                    more_details_body += f"\n\n---\n\n{workspace_diagnostic}\n\n---\n\n"
                
                more_details_body += """

The more specific details you provide, the faster we can help resolve your issue.

---
This message was sent by our 🤖 Brie IT Agent"""

                # TEMPORARY: Send to Matt for testing instead of original sender
                test_subject = f"[BRIE TEST] Need More Info for: {subject} (from {sender})"
                
                if send_email_response(access_token, "matthew.denecke@ever.ag", test_subject, more_details_body, subject):
                    delete_email(access_token, message_id)
                    log_email_processing(message_id, sender, subject, body, "STEP 3: Claude - Need More Info", 
                                       "Claude determined insufficient details", "Responded with questions and deleted", 
                                       more_details_body, attachments_info)
            
            else:
                print("Claude says sufficient but no wiki solution - deleting for IT team")
                delete_email(access_token, message_id)
                log_email_processing(message_id, sender, subject, body, "STEP 3: Claude - Sufficient Details", 
                                   "Claude determined sufficient details but no wiki solution", "Deleted - sent to IT team", 
                                   None, attachments_info)
                
    except Exception as e:
        print(f"Error processing email: {e}")

def user_already_tried_wiki_steps(user_message, wiki_content):
    """Check if user already mentioned trying steps from the wiki"""
    user_lower = user_message.lower()
    wiki_lower = wiki_content.lower()
    
    # Common indicators that user already tried troubleshooting
    tried_indicators = [
        "tried", "attempted", "already", "still", "doesn't work", "didn't work",
        "not working", "no luck", "same issue", "same problem", "persists"
    ]
    
    # Check if user mentioned trying something
    user_tried_something = any(indicator in user_lower for indicator in tried_indicators)
    
    if not user_tried_something:
        return False
    
    # Common troubleshooting steps to look for
    common_steps = [
        "restart", "reboot", "refresh", "clear cache", "update", "reinstall",
        "sign out", "log out", "close", "disable", "enable", "check"
    ]
    
    # Check if user mentioned trying steps that are likely in the wiki
    for step in common_steps:
        if step in user_lower and step in wiki_lower:
            return True
    
    return False

def lambda_handler(event, context):
    """Main Lambda handler for Brie IT Agent Office 365 integration"""
    
    # Check if this is a test Slack message request
    if event.get('send_test_slack'):
        print("Sending test message to Slack")
        access_token = get_access_token()
        
        if access_token:
            slack_email = "ddc-global-infrastruc-aaaachje7gjhbglxbdrxrqq4sm@dairy.slack.com"
            subject = "🚨 IT Automation Test - Distribution List Access"
            message = event.get('message', 'Test message from IT Automation System')
            
            success = send_email_response(access_token, slack_email, subject, message, "Test")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Slack test message sent successfully' if success else 'Failed to send Slack message'
                })
            }
        else:
            return {
                'statusCode': 500,
                'body': json.dumps({'message': 'Failed to get access token'})
            }
    
    # Check if this is a test security alert request
    if event.get('send_security_alert'):
        print("Sending test security alert to Slack")
        access_token = get_access_token()
        
        subject = "User at risk detected"
        body = """Contact: azure-noreply@microsoft.com
Status: Open
Priority: medium"""
        sender = "azure-noreply@microsoft.com"
        
        send_security_alert_to_slack(access_token, subject, body, sender)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Security alert sent to Slack successfully'})
        }
    
    try:
        print("Starting Brie IT Agent mailbox check")
        
        # Get access token
        access_token = get_access_token()
        if not access_token:
            return {'statusCode': 500, 'body': json.dumps({'message': 'Failed to get access token'})}
        
        # Get unread emails
        emails = get_unread_emails(access_token)
        print(f"Found {len(emails)} unread emails")
        
        # Process each email
        processed_count = 0
        for email in emails:
            process_email(access_token, email)
            processed_count += 1
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Processed {processed_count} emails successfully'
            })
        }
        
    except Exception as e:
        print(f"Error in Brie IT Agent: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': f'Error: {str(e)}'})
        }
