import json
import boto3
import re
import base64
import urllib.request
import urllib.parse
import os
from datetime import datetime

# Initialize AWS Bedrock for Claude
bedrock = boto3.client('bedrock-runtime')

# Confluence credentials
CONFLUENCE_EMAIL = "mdenecke@dairy.com"
CONFLUENCE_API_TOKEN = "ATLASSIAN_API_TOKEN=A2D8BE4C"
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

def generate_specific_questions(subject, description, sender_email):
    """Generate specific questions based on the issue type"""
    subject_lower = subject.lower() if subject else ""
    description_lower = description.lower() if description else ""
    
    base_questions = []
    
    # PC won't turn on issues
    if any(term in subject_lower + description_lower for term in ["won't turn on", "not turning on", "no power", "dead"]):
        base_questions = [
            "• What exactly happens when you press the power button? (No response, lights, fans, beeps?)",
            "• Are there any lights showing on the power adapter or computer?",
            "• Is the power cable securely connected to both the wall outlet and computer?",
            "• Have you tried a different power outlet?",
            "• When did this problem first start?",
            "• Were there any recent changes? (Windows updates, new software, power outages, etc.)"
        ]
    
    # Software/application issues
    elif any(term in subject_lower + description_lower for term in ["software", "application", "program", "app", "excel", "word", "outlook"]):
        base_questions = [
            "• What specific error message do you see? (Please provide exact text)",
            "• What were you trying to do when this happened?",
            "• Does this happen every time or only sometimes?",
            "• When did this problem start?",
            "• Have you tried restarting the application?",
            "• Are other programs working normally?"
        ]
    
    # Network/internet issues
    elif any(term in subject_lower + description_lower for term in ["internet", "network", "wifi", "connection", "can't connect"]):
        base_questions = [
            "• Are you unable to connect to WiFi or is the internet slow?",
            "• What device are you using? (Laptop, desktop, phone, etc.)",
            "• Are other devices working on the same network?",
            "• What error messages do you see?",
            "• When did this problem start?",
            "• Have you tried restarting your device and router?"
        ]
    
    # Generic questions for other issues
    else:
        base_questions = [
            "• What specific error messages do you see? (Please provide exact text)",
            "• What were you trying to do when this problem occurred?",
            "• What steps have you already tried to fix this?",
            "• When did this problem first start?",
            "• Does this happen every time or only in certain situations?"
        ]
    
    # Add contact info request if needed
    if not has_contact_info(sender_email, description):
        base_questions.append("• Please provide your name and phone number for follow-up")
    
    return base_questions

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
    
    # Extract meaningful keywords (3+ characters) - but keep them complete
    words = re.findall(r'\b[a-zA-Z]{3,}\b', cleaned)
    
    # Remove common stop words
    stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'man', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'its', 'let', 'put', 'say', 'she', 'too', 'use', 'thank', 'thanks'}
    
    keywords = [word.lower() for word in words if word.lower() not in stop_words]
    
    # Return first 4-5 most relevant keywords, but keep important phrases together
    result_keywords = []
    for i, word in enumerate(keywords):
        if len(result_keywords) >= 5:
            break
        result_keywords.append(word)
    
    return ' '.join(result_keywords)

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
        
        # Use simpler CQL syntax
        search_query = f'space = "IT" AND label = "foritchatbot" AND text ~ "{clean_query}"'
        encoded_query = urllib.parse.quote(search_query)
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/search?cql={encoded_query}&limit=5"
        
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
    """Convert HTML to plain text"""
    import re
    html_content = html_content.replace('<br/>', '\n').replace('<br>', '\n').replace('</p>', '\n\n')
    html_content = html_content.replace('<h2>', '\n## ').replace('</h2>', '\n')
    html_content = html_content.replace('<strong>', '**').replace('</strong>', '**')
    clean_text = re.sub(r'<[^>]+>', '', html_content)
    clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
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

def extract_required_info_from_wiki(wiki_content, user_message):
    """Extract the actual wiki requirements that the user hasn't provided"""
    if not wiki_content:
        return None
    
    wiki_lower = wiki_content.lower()
    user_lower = user_message.lower()
    
    # Check if user provided speed test results
    if "speed test" in wiki_lower or "speedtest.net" in wiki_lower:
        if "speed test" not in user_lower and "speedtest" not in user_lower:
            # Extract the actual speed test instructions from the wiki
            import re
            
            # Find speed test section in wiki content
            speed_test_match = re.search(r'(Open a web browser.*?providing the screenshots to IT again\.)', wiki_content, re.DOTALL | re.IGNORECASE)
            if speed_test_match:
                speed_test_instructions = speed_test_match.group(1)
                
                # Format the instructions properly with line breaks
                formatted_instructions = speed_test_instructions
                
                # Add line breaks after sentences
                formatted_instructions = re.sub(r'(\.) ([A-Z])', r'\1\n\n\2', formatted_instructions)
                
                # Add line breaks after numbered steps
                formatted_instructions = re.sub(r'(\d+\.) ', r'\n\1 ', formatted_instructions)
                
                # Clean up extra whitespace
                formatted_instructions = re.sub(r'\s+', ' ', formatted_instructions)
                formatted_instructions = re.sub(r'\n\s+', '\n', formatted_instructions)
                formatted_instructions = formatted_instructions.strip()
                
                return [formatted_instructions]
    
    return None

def process_email(access_token, email):
    """Process a single email with smart decision logic"""
    try:
        sender = email['from']['emailAddress']['address']
        subject = email['subject']
        body = email['body']['content'] if email['body']['contentType'] == 'text' else email['bodyPreview']
        message_id = email['id']
        
        print(f"Processing email from {sender}: {subject}")
        
        # STEP 1: Always search wiki FIRST
        search_query = f"{subject} {body}"
        wiki_result = search_confluence_wiki(search_query)
        
        if wiki_result:
            print(f"Found wiki solution: {wiki_result['title']}")
            
            # Check if user already provided details from the wiki
            required_info = extract_required_info_from_wiki(wiki_result.get('content', ''), body)
            
            if required_info:
                print("User missing required info from wiki - asking for specific details")
                required_text = "\n".join(required_info)
                
                more_details_body = f"""Hello,

I found information about your issue, but I need some additional details to help troubleshoot effectively:

{required_text}

Please provide this information so our IT team can assist you more quickly.

---
This message was sent by our 🤖 Brie IT Agent"""

                if send_email_response(access_token, sender, "Additional Information Needed", more_details_body, subject):
                    delete_email(access_token, message_id)
            
            elif user_already_tried_wiki_steps(body, wiki_result.get('content', '')):
                print("User already tried wiki steps - just deleting for IT team")
                delete_email(access_token, message_id)
            else:
                print("Sending concise wiki reference")
                wiki_title = wiki_result.get('title', 'Solution Found')
                wiki_url = wiki_result.get('url', '')
                
                solution_body = f"""Hello,

I found a solution for your issue. Please follow the troubleshooting steps in this article:

**{wiki_title}**

You can view the complete troubleshooting guide here: {wiki_url}

If this doesn't resolve your issue, please reply with the specific results and a member of our IT team will assist you further.

---
This message was sent by our 🤖 Brie IT Agent"""

                if send_email_response(access_token, sender, "Solution Found", solution_body, subject):
                    delete_email(access_token, message_id)
        
        else:
            print("No wiki solution found - using Claude analysis")
            
            # STEP 2: No wiki solution - use Claude to determine if we need more details
            if not is_ticket_detailed_enough(subject, body, sender):
                print("Claude says insufficient - asking for more details")
                
                # Generate specific questions based on issue type
                specific_questions = generate_specific_questions(subject, body, sender)
                questions_text = "\n".join(specific_questions)
                
                more_details_body = f"""Hello,

Thank you for contacting IT support. To help us resolve your issue quickly, please provide the following information:

{questions_text}

The more specific details you provide, the faster we can help resolve your issue.

---
This message was sent by our 🤖 Brie IT Agent"""

                if send_email_response(access_token, sender, "Need More Information", more_details_body, subject):
                    delete_email(access_token, message_id)
            
            else:
                print("Claude says sufficient but no wiki solution - deleting for IT team")
                delete_email(access_token, message_id)
                
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
