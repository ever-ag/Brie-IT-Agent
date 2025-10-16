#!/usr/bin/env python3
"""
IT Approval System Lambda Function - With Slack Buttons
Integrates with existing IT helpdesk bot for approve/deny workflow
"""

import json
import boto3
import uuid
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import os

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
sfn_client = boto3.client('stepfunctions')

# Slack configuration (same as IT helpdesk bot)
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', 'xoxb-2265620281-9422519481827-J4pfayoqFYi9wAtWHGH2StgJ')
IT_APPROVAL_CHANNEL = "C09KB40PL9J"  # IT channel ID

# DynamoDB table for tracking approvals
try:
    approvals_table = dynamodb.Table('it-approvals')
except:
    approvals_table = None
    print("⚠️ IT approvals table not available")

def send_slack_approval_with_buttons(approval_id, request_type, details, requester, urgency="normal", ticket_number=None, ticket_url=None, callback_params=None):
    """Send approval request to Slack with approve/deny buttons"""
    
    try:
        # Create urgency emoji
        urgency_emoji = "🚨" if urgency == "urgent" else "⚡" if urgency == "high" else "🚨"
        
        # Parse details to extract user and target for clean format
        users = "Unknown Users"
        target = "Unknown Target"
        
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
        message_text += f"*Type:* {request_type}\n"
        
        # Handle SSO Group requests specially
        if request_type == "SSO_GROUP" or "SSO" in request_type:
            if callback_params and 'ssoGroupRequest' in callback_params:
                sso = callback_params['ssoGroupRequest']
                action_verb = "Add" if sso.get('action') == 'add' else "Remove"
                message_text += f"*Action:* {action_verb}\n"
                message_text += f"*User:* {sso.get('user_email')}\n"
                message_text += f"*Group:* {sso.get('group_name')}\n"
                message_text += f"*Requested by:* {requester}"
            else:
                message_text += f"*Details:* {details}\n"
                message_text += f"*Requested by:* {requester}"
        elif "\n" in target:
            # Use appropriate label based on request type
            target_label = "Shared Mailboxes" if "Shared Mailbox" in request_type else "Groups"
            message_text += f"*User:* {users}\n*{target_label}:*\n{target}\n"
            message_text += f"*Requested by:* {requester}"
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

def create_approval_request(request_type, details, requester, callback_function=None, callback_params=None, urgency="normal", ticket_number=None, ticket_url=None, original_message_id=None, original_subject=None, task_token=None):
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
        'original_message_id': original_message_id,  # For email threading
        'original_subject': original_subject,  # For email threading
        'task_token': task_token  # For Step Functions integration
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
        
        # Check if expired
        if datetime.utcnow().isoformat() > approval['expires_at']:
            print(f"⚠️ Approval expired: {approval_id}")
            # Update status to expired
            approvals_table.update_item(
                Key={'approval_id': approval_id},
                UpdateExpression='SET #status = :status, processed_at = :timestamp',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'expired',
                    ':timestamp': datetime.utcnow().isoformat()
                }
            )
            return False
        
        # Determine new status
        new_status = 'approved' if action.upper() == 'APPROVE' else 'denied'
        
        # Update approval status only if still pending
        if approval['status'] == 'pending':
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
        else:
            print(f"⚠️ Approval already {approval['status']}, re-executing callback")
        
        # Send denial notification
        if new_status == 'denied':
            # Check if this is from IT Help Desk bot (not Brie)
            callback_params = approval.get('callback_params', {})
            email_data = callback_params.get('emailData', {})
            slack_context = email_data.get('slackContext')
            source = email_data.get('source')
            
            if source == 'it-helpdesk-bot' and slack_context:
                # Send Slack notification
                channel = slack_context.get('channel')
                if channel:
                    denial_msg = f"❌ **Request Denied**\n\nYour request was reviewed and denied. A live IT agent will follow up with you if needed."
                    slack_payload = {
                        'channel': channel,
                        'text': denial_msg
                    }
                    req = urllib.request.Request(
                        'https://slack.com/api/chat.postMessage',
                        data=json.dumps(slack_payload).encode('utf-8'),
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {SLACK_BOT_TOKEN}'
                        }
                    )
                    urllib.request.urlopen(req)
                    print(f"📱 Denial notification sent to Slack channel {channel}")
            else:
                # Send email for non-Slack requests
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
                        else:
                            print(f"❌ Failed to send denial reply for {approval_id}")
                    else:
                        print(f"❌ Missing original email details or access token for {approval_id}")
                except Exception as e:
                    print(f"❌ Error sending denial reply: {e}")
        
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
        
        # Execute callback if approved
        if new_status == 'approved':
            # Check if this is a Step Functions task token workflow
            if approval.get('task_token'):
                try:
                    # Send success to Step Functions
                    sfn_client.send_task_success(
                        taskToken=approval['task_token'],
                        output=json.dumps({
                            'approved': True,
                            'approver': approver,
                            'approval_id': approval_id,
                            'timestamp': int(datetime.utcnow().timestamp())
                        })
                    )
                    print(f"✅ Step Functions task token success sent for {approval_id}")
                except Exception as e:
                    print(f"❌ Error sending task success: {e}")
                    
            # Legacy callback function support
            elif approval.get('callback_function'):
                try:
                    # Invoke the callback Lambda function
                    callback_params = approval.get('callback_params', {})
                    callback_payload = {
                        'approval_id': approval_id,
                        'action': 'execute',
                        'params': callback_params,
                        'email_details': {
                            'original_message_id': approval['original_message_id'],
                            'original_subject': approval['original_subject'],
                            'requester': approval['requester'],
                            'approver': approver
                        }
                    }
                    
                    # Pass through emailData if it exists (contains slackContext)
                    if 'emailData' in callback_params:
                        callback_payload['params']['emailData'] = callback_params['emailData']
                    
                    # Execute asynchronously to avoid Slack timeout
                    response = lambda_client.invoke(
                        FunctionName=approval['callback_function'],
                        InvocationType='Event',  # Async
                        Payload=json.dumps(callback_payload)
                    )
                    
                    print(f"🚀 Callback function invoked: {approval['callback_function']}")
                    print("📧 Email will be sent after execution completes")
                    
                    # Notify it-helpdesk-bot to update conversation if Slack context exists
                    if 'emailData' in callback_params and 'slackContext' in callback_params['emailData']:
                        try:
                            # Extract resource name from callback_params (which has the Slack message blocks)
                            resource_name = None
                            import re
                            
                            # The callback_params contains the approval details with the full Slack message
                            # Look in callback_params for the formatted message
                            if 'callback_params' in approval:
                                cp = approval['callback_params']
                                # Convert to string to search through it
                                cp_str = str(cp)
                                # Look for all emails
                                email_matches = re.findall(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', cp_str)
                                # Get unique emails in order
                                unique_emails = []
                                for email in email_matches:
                                    if email not in unique_emails:
                                        unique_emails.append(email)
                                
                                # The target resource is the last unique email (requester is first)
                                if len(unique_emails) >= 2:
                                    resource_name = unique_emails[-1]  # Last unique email is the target
                                    print(f"Found resource from callback_params: {resource_name} (from {len(unique_emails)} unique emails)")
                            
                            if not resource_name:
                                print(f"Could not extract resource from approval data")
                            
                            lambda_client.invoke(
                                FunctionName='it-helpdesk-bot',
                                InvocationType='Event',
                                Payload=json.dumps({
                                    'approval_notification': True,
                                    'approval_data': {
                                        'approver': approver,
                                        'request_type': approval.get('request_type', 'Request'),
                                        'resource_name': resource_name,
                                        'slackContext': callback_params['emailData']['slackContext']
                                    }
                                })
                            )
                            print(f"✅ Sent approval notification to it-helpdesk-bot with resource: {resource_name}")
                        except Exception as e:
                            print(f"⚠️ Error sending approval notification: {e}")
                            import traceback
                            print(traceback.format_exc())
                    
                except Exception as e:
                    print(f"❌ Error invoking callback: {e}")
        
        # Handle denial for Step Functions
        elif new_status == 'denied' and approval.get('task_token'):
            try:
                sfn_client.send_task_failure(
                    taskToken=approval['task_token'],
                    error='ApprovalDenied',
                    cause=f'Request denied by {approver}'
                )
                print(f"❌ Step Functions task token failure sent for {approval_id}")
            except Exception as e:
                print(f"❌ Error sending task failure: {e}")
        
        # Execute callback if approved (legacy)
        if False:  # Disabled - moved above
                print(f"❌ Error invoking callback: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error processing approval response: {e}")
        return False

def get_pending_approvals():
    """Get all pending approval requests"""
    
    if not approvals_table:
        return []
    
    try:
        response = approvals_table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': 'pending'}
        )
        
        return response.get('Items', [])
        
    except Exception as e:
        print(f"❌ Error getting pending approvals: {e}")
        return []

def handle_slack_interaction(event, context):
    """Handle Slack button interactions from API Gateway"""
    import urllib.parse
    import json
    
    try:
        print(f"📥 Received API Gateway event: {json.dumps(event)}")
        
        # Parse the Slack payload
        body = event.get('body', '')
        print(f"📄 Raw body: {body}")
        
        if event.get('isBase64Encoded'):
            import base64
            body = base64.b64decode(body).decode('utf-8')
            print(f"📄 Decoded body: {body}")
        
        # Slack sends form-encoded data
        parsed_data = urllib.parse.parse_qs(body)
        print(f"📋 Parsed data: {parsed_data}")
        
        payload_str = parsed_data.get('payload', [''])[0]
        if not payload_str:
            print("❌ No payload found in request")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No payload found'})
            }
        
        payload = json.loads(payload_str)
        print(f"🎯 Slack payload: {json.dumps(payload)}")
        
        # Extract button action info
        action_id = payload['actions'][0]['action_id']
        user_id = payload['user']['id']
        user_name = payload['user']['name']
        
        print(f"🔘 Button action: {action_id} by {user_name}")
        
        # Parse approval ID and action from action_id (format: "approve_12345" or "deny_12345")
        if '_' in action_id:
            action_type = action_id.split('_', 1)[0]
            
            # Route resolution buttons to it-helpdesk-bot Lambda
            if action_type in ['resolved', 'needhelp', 'ticket']:
                print(f"🔀 Routing resolution button to it-helpdesk-bot: {action_id}")
                lambda_client = boto3.client('lambda')
                
                # Forward the entire event to it-helpdesk-bot
                response = lambda_client.invoke(
                    FunctionName='it-helpdesk-bot',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(event)
                )
                
                result = json.loads(response['Payload'].read())
                return result
            
            # Route engagement prompt buttons to it-helpdesk-bot
            if action_type == 'engagement':
                print(f"🔀 Routing engagement button to it-helpdesk-bot: {action_id}")
                lambda_client = boto3.client('lambda')
                
                # Forward the entire event to it-helpdesk-bot
                response = lambda_client.invoke(
                    FunctionName='it-helpdesk-bot',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(event)
                )
                
                result = json.loads(response['Payload'].read())
                return result
            
            # Route resumption buttons to it-helpdesk-bot
            if action_type in ['resumeyes', 'resumeno']:
                print(f"🔀 Routing resumption button to it-helpdesk-bot: {action_id}")
                lambda_client = boto3.client('lambda')
                
                # Forward the entire event to it-helpdesk-bot
                response = lambda_client.invoke(
                    FunctionName='it-helpdesk-bot',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(event)
                )
                
                result = json.loads(response['Payload'].read())
                return result
            
            # Route DL approval buttons to it-helpdesk-bot (they use it-actions table)
            if action_id.startswith('approve_dl_') or action_id.startswith('deny_dl_'):
                print(f"🔀 Routing DL approval to it-helpdesk-bot: {action_id}")
                lambda_client = boto3.client('lambda')
                
                # Forward the entire event to it-helpdesk-bot
                response = lambda_client.invoke(
                    FunctionName='it-helpdesk-bot',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(event)
                )
                
                result = json.loads(response['Payload'].read())
                return result
            
            # Route error recovery buttons to it-helpdesk-bot
            if action_id.startswith('error_ticket_') or action_id.startswith('error_retry_'):
                print(f"🔀 Routing error recovery to it-helpdesk-bot: {action_id}")
                lambda_client = boto3.client('lambda')
                
                # Forward the entire event to it-helpdesk-bot
                response = lambda_client.invoke(
                    FunctionName='it-helpdesk-bot',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(event)
                )
                
                result = json.loads(response['Payload'].read())
                return result
            
            # Handle other approval buttons (for it-approvals table)
            approval_id = action_id.split('_', 1)[1]
            
            # Process the approval response
            success = process_approval_response(
                approval_id=approval_id,
                action=action_type.upper(),  # APPROVE or DENY
                approver=user_name
            )
            
            if success:
                return {
                    'statusCode': 200,
                    'body': json.dumps({'text': f'✅ Request {action_type}d successfully'})
                }
            else:
                return {
                    'statusCode': 200,
                    'body': json.dumps({'text': '❌ Failed to process request'})
                }
        
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid action format'})
        }
        
    except Exception as e:
        print(f"❌ Error handling Slack interaction: {e}")
        import traceback
        print(f"📍 Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }

def get_graph_access_token():
    """Get Microsoft Graph access token for email operations"""
    TENANT_ID = "3d90a358-2976-40f4-8588-45ed47a26302"
    CLIENT_ID = "97d0a776-cc4a-4c2d-a774-fba7c66938f7"
    CLIENT_SECRET = os.environ.get('CLIENT_SECRET', '3bI8Q~FX-ABLIYxF0xYwpOpzmoBPSDUcBZHI-bD7')
    
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials'
    }
    
    encoded_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=encoded_data)
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
        return result.get('access_token')

def send_execution_result_email(original_message_id, original_subject, requester_email, success, message):
    """Send email notification about execution result using working email system"""
    try:
        # Use the same email system that works for denials
        session = boto3.Session()
        lambda_client = session.client('lambda')
        
        # Create email content
        if success:
            subject = f"✅ Request Approved and Completed - {original_subject}"
            body_content = f"""Your IT access request has been approved and completed successfully.

Result: {message}

Original Request: {original_subject}

Your access should now be active. If you have any issues, please contact IT support.

Best regards,
Brie IT Agent
Automated IT Support System"""
        else:
            subject = f"❌ Request Approved but Failed - {original_subject}"
            body_content = f"""Your IT access request was approved but encountered an issue during execution.

Issue: {message}

Original Request: {original_subject}

A live IT agent will review this request and complete it manually. You will receive another update once resolved.

Best regards,
Brie IT Agent
Automated IT Support System"""
        
        # Use the email processor that we know works
        email_payload = {
            'action': 'send_email',
            'to': requester_email,
            'subject': subject,
            'body': body_content,
            'original_message_id': original_message_id
        }
        
        # Send via email sender that exists
        response = lambda_client.invoke(
            FunctionName='brie-email-sender',
            InvocationType='Event',  # Async
            Payload=json.dumps(email_payload)
        )
        
        print(f"📧 Execution result email queued for {requester_email}")
        return True
                
    except Exception as e:
        print(f"❌ Error sending execution result email: {e}")
        return False

def lambda_handler(event, context):
    """Main Lambda handler for IT Approval System"""
    
    # Handle test email action
    if event.get('action') == 'test_email':
        success = send_execution_result_email(
            event.get('original_message_id'),
            event.get('original_subject'),
            event.get('requester_email'),
            event.get('success'),
            event.get('message')
        )
        
        return {
            'statusCode': 200 if success else 500,
            'body': json.dumps({
                'success': success,
                'message': 'Email test completed'
            })
        }
    
    # Handle API Gateway events (Slack button clicks)
    if 'httpMethod' in event:
        return handle_slack_interaction(event, context)
    
    action = event.get('action')
    
    if action == 'create_approval':
        # Create new approval request
        approval_id = create_approval_request(
            request_type=event.get('request_type') or event.get('approvalType'),
            details=event.get('details', ''),
            requester=event.get('requester') or event.get('emailData', {}).get('sender'),
            callback_function=event.get('callback_function'),
            callback_params=event.get('callback_params') or event.get('ssoGroupRequest'),
            urgency=event.get('urgency', 'normal'),
            ticket_number=event.get('ticket_number'),
            ticket_url=event.get('ticket_url'),
            original_message_id=event.get('original_message_id') or event.get('emailData', {}).get('messageId'),
            original_subject=event.get('original_subject') or event.get('emailData', {}).get('subject'),
            task_token=event.get('taskToken')
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
    
    elif action == 'get_pending':
        # Get pending approvals
        pending = get_pending_approvals()
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'pending_approvals': pending
            })
        }
    
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': 'Invalid action. Use: create_approval, process_response, or get_pending'
            })
        }

def get_access_token():
    """Get access token for Microsoft Graph API - exact same method as working Brie"""
    import urllib.request
    import urllib.parse
    import json
    import os
    
    # Use same working credentials as Brie
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
    """Send email reply using Microsoft Graph API with proper threading - EXACT SAME AS BRIE"""
    import urllib.request
    import json
    
    # TESTING MODE: Override recipient during testing
    TESTING_MODE = True
    TEST_EMAIL = "matthew.denecke@ever.ag"
    MAILBOX_EMAIL = "brieitagent@ever.ag"  # Same as Brie
    
    if TESTING_MODE:
        print(f"🧪 TESTING MODE: Redirecting email from {to_email} to {TEST_EMAIL}")
        to_email = TEST_EMAIL
    
    try:
        # Use exact same format as Brie
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
        
        # Use exact same URL format as Brie
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
                response_body = response.read().decode('utf-8')
                print(f"❌ Response body: {response_body}")
                return False
                
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error sending email reply: {e.code} {e.reason}")
        error_body = e.read().decode('utf-8')
        print(f"❌ Error details: {error_body}")
        return False
    except Exception as e:
        print(f"❌ Error sending email reply: {e}")
        return False

def send_email_via_graph(access_token, to_email, subject, body):
    """Send email using Microsoft Graph API"""
    import urllib.request
    import json
    
    # TESTING MODE: Override recipient during testing
    TESTING_MODE = True
    TEST_EMAIL = "matthew.denecke@ever.ag"
    
    if TESTING_MODE:
        print(f"🧪 TESTING MODE: Redirecting email from {to_email} to {TEST_EMAIL}")
        to_email = TEST_EMAIL
    
    try:
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
        
        email_data = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ]
            }
        }
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        data = json.dumps(email_data).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req) as response:
            return response.status == 202
            
    except Exception as e:
        print(f"Error sending email: {e}")
        return False
