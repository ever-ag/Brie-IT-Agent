import json
import boto3
import re
import base64
import urllib.request
import urllib.parse
import email
from datetime import datetime

# Confluence credentials
CONFLUENCE_EMAIL = "mdenecke@dairy.com"
CONFLUENCE_API_TOKEN = "ATLASSIAN_API_TOKEN=A2D8BE4C"
CONFLUENCE_BASE_URL = "https://everag.atlassian.net/wiki"
CONFLUENCE_SPACE_KEY = "IT"

# Email settings
EMAIL_USER = "brieitagent@ever.ag"

def is_ticket_detailed_enough(subject, description):
    """Check if ticket has enough details to search for solutions"""
    
    # Check subject
    if not subject or len(subject.strip()) < 10:
        return False
    
    # Check for vague subjects
    vague_subjects = [
        "help", "issue", "problem", "not working", "broken", "error", 
        "can't", "unable", "need help", "assistance", "support"
    ]
    
    subject_lower = subject.lower()
    if any(vague in subject_lower for vague in vague_subjects) and len(subject.strip()) < 20:
        return False
    
    # Check description
    if not description or len(description.strip()) < 30:
        return False
    
    # Check for minimal descriptions
    minimal_descriptions = [
        "not working", "broken", "help", "issue", "problem", "error",
        "can you help", "need assistance", "please fix"
    ]
    
    description_lower = description.lower()
    if any(minimal in description_lower for minimal in minimal_descriptions) and len(description.strip()) < 50:
        return False
    
    return True

def search_confluence_wiki(query_text):
    """Search Confluence for pages with foritchatbot label"""
    
    try:
        # Create authentication header
        auth_string = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        # Search query - look for pages with foritchatbot label
        search_query = f'space="{CONFLUENCE_SPACE_KEY}" AND label="foritchatbot" AND text~"{query_text}"'
        encoded_query = urllib.parse.quote(search_query)
        
        search_url = f"{CONFLUENCE_BASE_URL}/rest/api/search?cql={encoded_query}&limit=5"
        
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Basic {auth_b64}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                results = json.loads(response.read().decode('utf-8'))
                
                if results.get('results') and len(results['results']) > 0:
                    # Get the best match (first result)
                    best_match = results['results'][0]
                    page_id = best_match['content']['id']
                    
                    # Get full page content
                    page_content = get_page_content(page_id)
                    return {
                        'title': best_match['content']['title'],
                        'url': f"{CONFLUENCE_BASE_URL}/spaces/{CONFLUENCE_SPACE_KEY}/pages/{page_id}",
                        'content': page_content
                    }
                
                return None
            else:
                print(f"Search failed: {response.status}")
                return None
                
    except Exception as e:
        print(f"Error searching Confluence: {e}")
        return None

def get_page_content(page_id):
    """Get the content of a Confluence page"""
    
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
                
                # Extract and clean HTML content
                html_content = page_data['body']['storage']['value']
                
                # Simple HTML to text conversion
                text_content = html_to_text(html_content)
                return text_content
            else:
                return "Content not available"
                
    except Exception as e:
        print(f"Error getting page content: {e}")
        return "Content not available"

def html_to_text(html_content):
    """Convert HTML to plain text"""
    
    # Remove HTML tags
    import re
    
    # Replace common HTML elements with text equivalents
    html_content = html_content.replace('<br/>', '\n')
    html_content = html_content.replace('<br>', '\n')
    html_content = html_content.replace('</p>', '\n\n')
    html_content = html_content.replace('<h2>', '\n## ')
    html_content = html_content.replace('</h2>', '\n')
    html_content = html_content.replace('<h3>', '\n### ')
    html_content = html_content.replace('</h3>', '\n')
    html_content = html_content.replace('<strong>', '**')
    html_content = html_content.replace('</strong>', '**')
    html_content = html_content.replace('<em>', '*')
    html_content = html_content.replace('</em>', '*')
    
    # Remove all remaining HTML tags
    clean_text = re.sub(r'<[^>]+>', '', html_content)
    
    # Clean up whitespace
    clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
    clean_text = clean_text.strip()
    
    return clean_text

def send_email_response(to_email, subject, body, original_subject):
    """Send email response using AWS SES"""
    
    try:
        # Use AWS SES
        ses_client = boto3.client('ses', region_name='us-east-1')
        
        response = ses_client.send_email(
            Source=EMAIL_USER,
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': f"Re: {original_subject}"},
                'Body': {'Text': {'Data': body}}
            }
        )
        
        print(f"Email sent successfully to {to_email} via SES")
        return True
        
    except Exception as e:
        print(f"Error sending email via SES: {e}")
        return False

def parse_forwarded_ticket(email_content):
    """Parse forwarded ticket email to extract original sender, subject, and description"""
    
    try:
        # Parse the email
        msg = email.message_from_string(email_content)
        
        # Extract original sender from forwarded email
        original_sender = None
        original_subject = None
        original_description = None
        
        # Get email body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode('utf-8')
                    break
        else:
            body = msg.get_payload(decode=True).decode('utf-8')
        
        # Look for patterns in forwarded emails
        lines = body.split('\n')
        
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            
            # Look for original sender
            if 'from:' in line_lower or 'sender:' in line_lower:
                original_sender = line.split(':', 1)[1].strip()
                # Extract email from "Name <email>" format
                email_match = re.search(r'<([^>]+)>', original_sender)
                if email_match:
                    original_sender = email_match.group(1)
                elif '@' not in original_sender:
                    # Look for email in next line
                    if i + 1 < len(lines) and '@' in lines[i + 1]:
                        original_sender = lines[i + 1].strip()
            
            # Look for original subject
            elif 'subject:' in line_lower:
                original_subject = line.split(':', 1)[1].strip()
            
            # Look for description/body (usually after headers)
            elif line.strip() == '' and i > 5:  # Empty line after headers
                # Rest is description
                original_description = '\n'.join(lines[i+1:]).strip()
                break
        
        # If we couldn't parse the forwarded format, use the email subject/body directly
        if not original_subject:
            original_subject = msg.get('Subject', '')
        
        if not original_description:
            original_description = body
        
        if not original_sender:
            original_sender = msg.get('From', '')
        
        return {
            'sender': original_sender,
            'subject': original_subject,
            'description': original_description
        }
        
    except Exception as e:
        print(f"Error parsing forwarded ticket: {e}")
        return None

def lambda_handler(event, context):
    """Main Lambda handler for Brie IT Agent"""
    
    try:
        # Handle SES email event (direct content like existing system)
        if 'Records' in event:
            for record in event['Records']:
                if record.get('eventSource') == 'aws:ses':
                    
                    # Get email content directly from SES (like existing system)
                    ses_mail = record['ses']['mail']
                    
                    # Extract email content from the SES event
                    email_content = ""
                    if 'content' in record['ses']:
                        email_content = record['ses']['content']
                    else:
                        # Build email content from SES mail object
                        email_content = f"From: {ses_mail.get('commonHeaders', {}).get('from', [''])[0]}\n"
                        email_content += f"To: {ses_mail.get('commonHeaders', {}).get('to', [''])[0]}\n"
                        email_content += f"Subject: {ses_mail.get('commonHeaders', {}).get('subject', '')}\n\n"
                        
                        # For now, we'll work with headers - full content would need S3 retrieval
                        # But let's try the direct approach first
                        print("No direct content available, using headers only")
                    
                    if not email_content:
                        print("No email content found")
                        continue
                    
                    print(f"Processing email content: {email_content[:200]}...")
                    
                    # Parse the forwarded ticket
                    ticket_info = parse_forwarded_ticket(email_content)
                    
                    if not ticket_info:
                        print("Could not parse ticket information")
                        continue
                    
                    print(f"Parsed ticket - Sender: {ticket_info['sender']}, Subject: {ticket_info['subject']}")
                    
                    # Check if ticket has enough details
                    if not is_ticket_detailed_enough(ticket_info['subject'], ticket_info['description']):
                        print("Ticket needs more details - sending request for more info")
                        
                        # Send "need more details" response
                        more_details_body = f"""Hello,

Thank you for contacting IT support. To better assist you, we need more information about your issue.

Please provide:
• A detailed description of the problem
• What you were trying to do when the issue occurred
• Any error messages you received
• Steps you've already tried to resolve the issue

The more details you provide, the faster we can help resolve your issue.

Best regards,
Brie IT Agent
Ever.Ag IT Support"""

                        send_email_response(
                            ticket_info['sender'],
                            "Need More Information",
                            more_details_body,
                            ticket_info['subject']
                        )
                        
                    else:
                        print("Ticket has sufficient details - searching for solutions")
                        
                        # Search for wiki solutions
                        search_query = f"{ticket_info['subject']} {ticket_info['description']}"
                        wiki_result = search_confluence_wiki(search_query)
                        
                        if wiki_result:
                            print(f"Found wiki solution: {wiki_result['title']}")
                            
                            # Send wiki solution response
                            solution_body = f"""Hello,

I found a solution that may help with your issue:

**{wiki_result['title']}**

{wiki_result['content']}

For more details, you can view the full article here: {wiki_result['url']}

If this doesn't resolve your issue, please reply and a member of our IT team will assist you further.

Best regards,
Brie IT Agent
Ever.Ag IT Support"""

                            send_email_response(
                                ticket_info['sender'],
                                "Possible Solution Found",
                                solution_body,
                                ticket_info['subject']
                            )
                            
                        else:
                            print("No wiki solution found - deleting email (no response)")
                            # No action needed - email will be processed and deleted
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Brie IT Agent processed successfully'})
        }
        
    except Exception as e:
        print(f"Error in Brie IT Agent: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': f'Error: {str(e)}'})
        }
