def is_connection_issue(subject, body):
    """Detect if this is a connection-related issue"""
    text = f"{subject} {body}".lower()
    
    connection_keywords = [
        'slow', 'slowness', 'connection', 'connect', 'disconnect', 'vpn', 
        'workspace', 'aws workspace', 'network', 'internet', 'latency',
        'timeout', 'lag', 'loading', 'buffering', 'frozen', 'freeze',
        'not working', 'broken', 'down', 'offline', 'online'
    ]
    
    return any(keyword in text for keyword in connection_keywords)

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

def process_email(access_token, email):
    """Process email with connection issue detection"""
    try:
        sender = email['from']['emailAddress']['address']
        subject = email['subject']
        body = email['body']['content'] if email['body']['contentType'] == 'text' else email['bodyPreview']
        message_id = email['id']
        
        print(f"Processing email from {sender}: {subject}")
        
        # Check if this is a connection issue
        if is_connection_issue(subject, body):
            print("Detected connection issue - sending standardized response")
            
            connection_response = get_connection_issue_response()
            
            if send_email_response(access_token, sender, "Connection Issue - Speed Test Required", connection_response, subject):
                delete_email(access_token, message_id)
                print("Connection issue response sent and email deleted")
        else:
            print("Not a connection issue - using original logic")
            # Fall back to original wiki search logic here
            # ... (keep existing logic for non-connection issues)
            
    except Exception as e:
        print(f"Error processing email: {e}")
