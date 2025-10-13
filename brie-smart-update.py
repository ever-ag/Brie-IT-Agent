def extract_required_info_from_wiki(wiki_content, user_message):
    """Extract what the user needs to provide based on wiki requirements"""
    if not wiki_content:
        return None
    
    wiki_lower = wiki_content.lower()
    user_lower = user_message.lower()
    
    required_items = []
    
    # Speed test requirements
    if "speed test" in wiki_lower or "speedtest.net" in wiki_lower:
        if "speed test" not in user_lower and "speedtest" not in user_lower:
            required_items.append("• Speed test results from speedtest.net (screenshot from your computer and mobile device)")
    
    # Connection type
    if "ethernet" in wiki_lower or "wi-fi" in wiki_lower or "wifi" in wiki_lower:
        if "ethernet" not in user_lower and "wifi" not in user_lower and "wi-fi" not in user_lower:
            required_items.append("• Are you connected via Ethernet cable or Wi-Fi?")
    
    # Timing information
    if "when" in wiki_lower and ("start" in wiki_lower or "occur" in wiki_lower):
        if "started" not in user_lower and "began" not in user_lower and "when" not in user_lower:
            required_items.append("• When did this problem start?")
    
    # AWS Workspace specific
    if "aws workspace" in user_lower or "workspace" in user_lower:
        if "latency" in wiki_lower and "cloudwatch" in wiki_lower:
            required_items.append("• Please visit https://clients.amazonworkspaces.com/Health.html and provide a screenshot")
    
    return required_items if required_items else None

def user_already_tried_wiki_steps(user_message, wiki_content):
    """Check if user already mentioned trying steps from the wiki"""
    user_lower = user_message.lower()
    wiki_lower = wiki_content.lower() if wiki_content else ""
    
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
