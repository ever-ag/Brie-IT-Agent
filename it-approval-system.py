#!/usr/bin/env python3
"""
IT Approval System Lambda Function - Fixed to use actual callback results
"""

import json
import boto3
import uuid
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import os
from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

# Slack configuration
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', 'xoxb-2265620281-9422519481827-J4pfayoqFYi9wAtWHGH2StgJ')
IT_APPROVAL_CHANNEL = "C09KB40PL9J"  # Use the working approval channel

# DynamoDB table for tracking approvals
try:
    approvals_table = dynamodb.Table('it-approvals')
except:
    approvals_table = None
    print("⚠️ IT approvals table not available")

def process_approval_response(approval_id, action, approver):
    """Process approval/denial response from Slack buttons"""
    
    if not approvals_table:
        print("❌ Approvals table not available")
        return False
    
    try:
        # Get approval request
        response = approvals_table.get_item(Key={'approval_id': approval_id})
        
        if 'Item' not in response:
            print(f"❌ Approval request not found: {approval_id}")
            return False
        
        approval = response['Item']
        
        # Check if already processed
        if approval['status'] != 'pending':
            print(f"⚠️ Approval already processed: {approval_id} - {approval['status']}")
            return False
        
        # Update approval status
        new_status = 'approved' if action.lower() == 'approved' else 'denied'
        
        approvals_table.update_item(
            Key={'approval_id': approval_id},
            UpdateExpression='SET #status = :status, approver = :approver, processed_at = :timestamp',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': new_status,
                ':approver': approver,
                ':timestamp': datetime.utcnow().isoformat()
            }
        )
        
        print(f"✅ Approval {new_status}: {approval_id} by {approver}")
        
        # Send confirmation to Slack
        status_emoji = "✅" if new_status == 'approved' else "❌"
        action_text = "approved" if new_status == 'approved' else "denied"
        confirmation_message = {
            "channel": IT_APPROVAL_CHANNEL,
            "text": f"{status_emoji} {approver} {action_text} this request"
        }
        
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        data = json.dumps(confirmation_message).encode('utf-8')
        req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
        
        try:
            with urllib.request.urlopen(req) as response:
                print(f"📧 Confirmation sent to Slack")
        except Exception as e:
            print(f"⚠️ Error sending confirmation: {e}")
        
        # Handle approval/denial
        if new_status == 'denied':
            # Send denial email
            try:
                access_token = get_access_token()
                if access_token and approval.get('original_message_id') and approval.get('original_subject'):
                    denial_body = f"""Sorry, the Brie IT Agent can't approve your request. A Live IT Help Desk Agent will get back to you.

Request Information:
{approval['details']}

Requested by: {approval['requester']}

---
Brie IT Agent"""

                    success = send_email_reply_via_graph(
                        access_token, 
                        approval['requester'], 
                        approval['original_subject'], 
                        denial_body,
                        approval['original_message_id']
                    )
                    if success:
                        print(f"📧 Denial reply sent to {approval['requester']} for {approval_id}")
            except Exception as e:
                print(f"❌ Error sending denial reply: {e}")
        
        elif new_status == 'approved' and approval.get('callback_function'):
            # Execute callback and wait for result
            try:
                callback_payload = {
                    'approval_id': approval_id,
                    'action': 'execute',
                    'params': approval.get('callback_params', {}),
                    'email_details': {
                        'original_message_id': approval['original_message_id'],
                        'original_subject': approval['original_subject'],
                        'requester': approval['requester']
                    }
                }
                
                # Execute SYNCHRONOUSLY to get the actual result
                response = lambda_client.invoke(
                    FunctionName=approval['callback_function'],
                    InvocationType='RequestResponse',  # Synchronous
                    Payload=json.dumps(callback_payload, cls=DecimalEncoder)
                )
                
                # Parse the response
                response_payload = json.loads(response['Payload'].read())
                print(f"🔍 Callback response: {response_payload}")
                
                # Extract the actual result
                if response_payload.get('statusCode') == 200:
                    body = json.loads(response_payload.get('body', '{}'))
                    success = body.get('success', False)
                    message = body.get('message', 'Unknown result')
                else:
                    success = False
                    message = f"Execution failed with status {response_payload.get('statusCode')}"
                
                # Send email with actual result
                send_execution_result_email(
                    approval['original_message_id'],
                    approval['original_subject'],
                    approval['requester'],
                    success,
                    message
                )
                
                print(f"📧 Execution result email sent: {success} - {message}")
                
            except Exception as e:
                print(f"❌ Error executing callback: {e}")
                # Send failure email
                send_execution_result_email(
                    approval['original_message_id'],
                    approval['original_subject'],
                    approval['requester'],
                    False,
                    f"System error during execution: {str(e)}"
                )
        
        return True
        
    except Exception as e:
        print(f"❌ Error processing approval response: {e}")
        return False

def send_execution_result_email(original_message_id, original_subject, requester_email, success, message):
    """Send email notification about execution result"""
    try:
        # Create email content based on actual result
        if success:
            if "already has access" in message or "already a member" in message:
                subject = f"✅ Access Confirmed - {original_subject}"
                body_content = f"""Your IT access request has been reviewed.

Result: {message}

Original Request: {original_subject}

No changes were needed as you already have the requested access.

--
Brie IT Agent
Automated IT Support System"""
            else:
                subject = f"✅ Request Approved and Completed - {original_subject}"
                body_content = f"""Your IT access request has been approved and completed successfully.

Result: {message}

Original Request: {original_subject}

--
Brie IT Agent
Automated IT Support System"""
        else:
            subject = f"❌ Request Approved but Failed - {original_subject}"
            body_content = f"""Your IT access request was approved but encountered an issue during execution.

Issue: {message}

Original Request: {original_subject}

A live IT agent will review this request and complete it manually. You will receive another update once resolved.

--
Brie IT Agent
Automated IT Support System"""
        
        # Send via email sender
        email_payload = {
            'action': 'send_email',
            'to': requester_email,
            'subject': subject,
            'body': body_content,
            'original_message_id': original_message_id
        }
        
        response = lambda_client.invoke(
            FunctionName='brie-email-sender',
            InvocationType='Event',  # Async for email sending
            Payload=json.dumps(email_payload, cls=DecimalEncoder)
        )
        
        print(f"📧 Execution result email queued for {requester_email}")
        return True
                
    except Exception as e:
        print(f"❌ Error sending execution result email: {e}")
        return False

def get_access_token():
    """Get access token for Microsoft Graph API"""
    import urllib.request
    import urllib.parse
    import json
    import os
    
    TENANT_ID = "3d90a358-2976-40f4-8588-45ed47a26302"
    CLIENT_ID = "97d0a776-cc4a-4c2d-a774-fba7c66938f7"
    CLIENT_SECRET = os.environ.get('CLIENT_SECRET', '3bI8Q~FX-ABLIYxF0xYwpOpzmoBPSDUcBZHI-bD7')
    
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

def send_email_reply_via_graph(access_token, to_email, original_subject, body, original_message_id):
    """Send email reply using Microsoft Graph API"""
    import urllib.request
    import json
    
    TESTING_MODE = True
    TEST_EMAIL = "matthew.denecke@ever.ag"
    MAILBOX_EMAIL = "brieitagent@ever.ag"
    
    if TESTING_MODE:
        print(f"🧪 TESTING MODE: Redirecting email from {to_email} to {TEST_EMAIL}")
        to_email = TEST_EMAIL
    
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
                print(f"✅ Email sent successfully to {to_email}")
                return True
            else:
                print(f"❌ Email reply failed with status: {response.status}")
                return False
                
    except Exception as e:
        print(f"❌ Error sending email reply: {e}")
        return False

def send_slack_approval_with_buttons(approval_id, request_type, details, requester, urgency="normal", ticket_number=None, ticket_url=None, callback_params=None):
    """Send approval request to Slack with approve/deny buttons"""
    
    try:
        # Set request type display and urgency emoji
        type_display = request_type or "SSO_GROUP"
        urgency_emoji = "🚨" if urgency == "urgent" else "⚡" if urgency == "high" else "🚨"
        
        # Parse details to extract user and target for clean format
        users = "Unknown Users"
        target = "Unknown Target"
        
        # Extract user and group from details or callback_params
        if details:
            # Try to parse from details string
            if "User:" in details and "Group:" in details:
                lines = details.split('\n')
                for line in lines:
                    if line.startswith('User:'):
                        users = line.replace('User:', '').strip()
                    elif line.startswith('Group:'):
                        target = line.replace('Group:', '').strip()
        
        # Extract from callback_params if available (more reliable)
        if callback_params and 'plan' in callback_params:
            plan = callback_params['plan']
            
            # Get users
            if 'users' in plan and plan['users']:
                users = ", ".join(plan['users'])
            
            # Get targets (groups or mailboxes) - prioritize full email addresses
            targets = []
            if 'groups' in plan:
                for group in plan['groups']:
                    if 'email' in group:
                        targets.append(group['email'])
                    elif 'group_name' in group:
                        targets.append(group['group_name'])
            elif 'mailboxes' in plan:
                for mailbox in plan['mailboxes']:
                    if 'email' in mailbox:
                        targets.append(mailbox['email'])
                    elif 'name' in mailbox:
                        targets.append(mailbox['name'])
            
            if targets:
                target = "\n".join([f"   • {t}" for t in targets])
        
        # Fallback to parsing details string
        if users == "Unknown Users" and "User(s):" in details:
            lines = details.split('\n')
            for line in lines:
                if line.startswith("User(s):"):
                    users = line.replace("User(s):", "").strip()
                elif line.startswith("Target(s):"):
                    target = line.replace("Target(s):", "").strip()
                elif line.startswith("Shared Mailbox(es):"):
                    target = line.replace("Shared Mailbox(es):", "").strip()
        
        # Build minimal message text
        message_text = f"*{urgency_emoji} IT Automation Approval Request*\n\n"
        message_text += f"*Type:* {type_display}\n"
        if "\n" in target:
            # Use appropriate label based on request type
            target_label = "Shared Mailboxes" if "Shared Mailbox" in request_type else "Groups"
            message_text += f"*User:* {users}\n*{target_label}:*\n{target}\n"
        else:
            message_text += f"*User:* {users} → {target}\n"
        message_text += f"*Requested by:* {requester}"
        
        # Add ticket info only if available
        if ticket_number and ticket_url:
            message_text += f"\n\n*Ticket Number:* {ticket_number}\n"
            message_text += f"You can view or update this ticket at any point - <{ticket_url}|Go to ticket>"
        elif ticket_number:
            message_text += f"\n\n*Ticket Number:* {ticket_number}"
        
        # Create approval message with buttons
        approval_message = {
            "channel": IT_APPROVAL_CHANNEL,
            "text": f"{urgency_emoji} IT Automation Approval Request",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message_text
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
        
        # Send to Slack using bot token
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        data = json.dumps(approval_message).encode('utf-8')
        req = urllib.request.Request('https://slack.com/api/chat.postMessage', data=data, headers=headers)
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            
            if result.get('ok'):
                print(f"📧 Approval request sent to Slack: {approval_id}")
                return True
            else:
                print(f"❌ Slack API error: {result.get('error', 'Unknown error')}")
                return False
        
    except Exception as e:
        print(f"❌ Error sending Slack approval: {e}")
        return False

def create_approval_request(request_type, details, requester, callback_function=None, callback_params=None, urgency="normal", ticket_number=None, ticket_url=None, original_message_id=None, original_subject=None):
    """Create a new approval request"""
    
    approval_id = str(uuid.uuid4())[:8]  # Short ID for easy reference
    timestamp = datetime.utcnow().isoformat()
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    
    approval_record = {
        'approval_id': approval_id,
        'request_type': request_type,
        'details': details,
        'requester': requester,
        'status': 'pending',
        'created_at': timestamp,
        'expires_at': expires_at,
        'callback_function': callback_function,
        'callback_params': callback_params or {},
        'urgency': urgency,
        'ticket_number': ticket_number,
        'ticket_url': ticket_url,
        'original_message_id': original_message_id,
        'original_subject': original_subject
    }
    
    # Store in DynamoDB
    if approvals_table:
        try:
            approvals_table.put_item(Item=approval_record)
            print(f"✅ Approval request created: {approval_id}")
        except Exception as e:
            print(f"❌ Error storing approval request: {e}")
            return None
    
    # Send to Slack with buttons
    if send_slack_approval_with_buttons(approval_id, request_type, details, requester, urgency, ticket_number, ticket_url, callback_params):
        return approval_id
    else:
        return None

def handle_slack_interaction(event, context):
    """Handle Slack button interactions"""
    print(f"🔔 BUTTON HANDLER INVOKED - Event keys: {list(event.keys())}")
    try:
        body = event.get('body', '')
        print(f"📦 Body length: {len(body)}")
        parsed_data = urllib.parse.parse_qs(body)
        print(f"📦 Parsed data keys: {list(parsed_data.keys())}")
        
        if 'payload' in parsed_data:
            payload = json.loads(parsed_data['payload'][0])
            print(f"📦 Payload type: {payload.get('type')}")
            
            if payload.get('type') == 'block_actions':
                action = payload['actions'][0]['action_id']
                user = payload['user']['username']
                print(f"🔘 Button clicked: {action} by {user}")
                
                if action.startswith('approve_'):
                    approval_id = action.replace('approve_', '')
                    print(f"✅ APPROVING: {approval_id}")
                    process_approval_response(approval_id, 'approved', user)
                    return {'statusCode': 200, 'body': json.dumps({'message': 'Approved'})}
                elif action.startswith('deny_'):
                    approval_id = action.replace('deny_', '')
                    print(f"❌ DENYING: {approval_id}")
                    process_approval_response(approval_id, 'denied', user)
                    return {'statusCode': 200, 'body': json.dumps({'message': 'Denied'})}
        else:
            print(f"⚠️ No payload in parsed data")
        
        return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid request'})}
    except Exception as e:
        print(f"❌ Error handling interaction: {e}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def lambda_handler(event, context):
    """Main Lambda handler for IT Approval System"""
    print(f"🚀 LAMBDA INVOKED - Event keys: {list(event.keys())}")
    print(f"🚀 Has httpMethod: {'httpMethod' in event}")
    print(f"🚀 Action: {event.get('action', 'NONE')}")
    
    # Handle API Gateway events (Slack button clicks)
    if 'httpMethod' in event:
        print(f"🌐 Routing to handle_slack_interaction")
        return handle_slack_interaction(event, context)
    
    action = event.get('action')
    
    if action == 'create_approval':
        # Create new approval request
        approval_id = create_approval_request(
            request_type=event.get('request_type'),
            details=event.get('details'),
            requester=event.get('requester'),
            callback_function=event.get('callback_function'),
            callback_params=event.get('callback_params'),
            urgency=event.get('urgency', 'normal'),
            ticket_number=event.get('ticket_number'),
            ticket_url=event.get('ticket_url'),
            original_message_id=event.get('original_message_id'),
            original_subject=event.get('original_subject')
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'approval_id': approval_id,
                'status': 'pending' if approval_id else 'failed'
            })
        }
    
    elif action == 'process_response':
        # Process approval/denial response from Slack buttons
        success = process_approval_response(
            approval_id=event.get('approval_id'),
            action=event.get('response'),  # APPROVE or DENY
            approver=event.get('approver')
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': success
            })
        }
    
    # Other actions...
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': 'Invalid action'
            })
        }
