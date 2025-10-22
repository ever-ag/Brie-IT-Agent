#!/usr/bin/env python3
"""
IT Approval System Lambda Function - Fixed to notify bot after processing
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

# DynamoDB table
approvals_table = None
try:
    approvals_table = dynamodb.Table('it-approvals')
except Exception as e:
    print(f"Warning: Could not connect to DynamoDB table: {e}")

# Slack configuration
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL', 'C09KB40PL9J')  # IT channel

def notify_bot_approval_processed(approval_id, status, result_message, slack_context, interaction_id=None, approver=None, request_data=None):
    """Notify the bot that an approval has been processed"""
    try:
        callback_payload = {
            'action': 'approval_processed',
            'approval_id': approval_id,
            'status': status,  # 'approved' or 'denied'
            'result_message': result_message,
            'slack_context': slack_context,
            'approver': approver
        }
        
        # Add interaction_id if available
        if interaction_id:
            callback_payload['slack_context']['interaction_id'] = interaction_id
            
        # Add request details if available
        if request_data:
            # Handle both SSO groups and shared mailboxes
            resource = request_data.get('group_name') or request_data.get('mailbox_email')
            callback_payload.update({
                'user_email': request_data.get('user_email'),
                'group_name': request_data.get('group_name'),
                'mailbox_email': request_data.get('mailbox_email'),
                'resource_name': resource,
                'action_taken': 'Already a member' if 'already a member' in result_message.lower() else 'Added to group'
            })
        
        print(f"🔔 Notifying bot of approval {approval_id} status: {status}")
        
        response = lambda_client.invoke(
            FunctionName='it-helpdesk-bot',
            InvocationType='Event',  # Asynchronous
            Payload=json.dumps(callback_payload, cls=DecimalEncoder)
        )
        
        print(f"✅ Bot notification sent for approval {approval_id}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to notify bot: {str(e)}")
        return False

def process_approval_response(approval_id, action, approver):
    """Process approval or denial response"""
    
    if not approvals_table:
        print("❌ No DynamoDB table available")
        return False
    
    try:
        # Get approval record
        response = approvals_table.get_item(Key={'approval_id': approval_id})
        
        if 'Item' not in response:
            print(f"❌ Approval {approval_id} not found")
            return False
        
        approval = response['Item']
        
        # Update status
        new_status = 'approved' if action == 'APPROVE' else 'denied'
        
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
        send_slack_confirmation(approval_id, new_status, approver, approval.get('request_type', 'Unknown'))
        
        result_message = "Request processed successfully"
        
        if new_status == 'denied':
            result_message = f"Request denied by {approver}"
            # Notify bot of denial
            notify_bot_approval_processed(
                approval_id=approval_id,
                status='denied',
                result_message=result_message,
                slack_context=approval.get('callback_params', {}).get('emailData', {}).get('slackContext', {}),
                interaction_id=approval.get('callback_params', {}).get('interaction_id'),
                approver=approver,
                request_data=approval.get('callback_params', {}).get('ssoGroupRequest', {})
            )
        
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
                
                result_message = message
                
                # Send email with actual result
                send_execution_result_email(
                    approval['original_message_id'],
                    approval['original_subject'],
                    approval['requester'],
                    success,
                    message
                )
                
                print(f"📧 Execution result email sent: {success} - {message}")
                
                # **NOTIFY BOT OF COMPLETION**
                # Extract resource data based on request type
                request_data = {}
                callback_params = approval.get('callback_params', {})
                
                if callback_params.get('ssoGroupRequest'):
                    request_data = callback_params['ssoGroupRequest']
                elif callback_params.get('mailbox_email'):
                    # Shared mailbox request
                    request_data = {
                        'mailbox_email': callback_params.get('mailbox_email'),
                        'user_email': callback_params.get('user_email')
                    }
                
                notify_bot_approval_processed(
                    approval_id=approval_id,
                    status='approved',
                    result_message=result_message,
                    slack_context=callback_params.get('emailData', {}).get('slackContext', {}),
                    interaction_id=callback_params.get('interaction_id'),
                    approver=approver,
                    request_data=request_data
                )
                
            except Exception as e:
                print(f"❌ Error executing callback: {e}")
                result_message = f"System error during execution: {str(e)}"
                
                # Send failure email
                send_execution_result_email(
                    approval['original_message_id'],
                    approval['original_subject'],
                    approval['requester'],
                    False,
                    result_message
                )
                
                # Notify bot of failure
                # Extract resource data based on request type
                request_data = {}
                callback_params = approval.get('callback_params', {})
                
                if callback_params.get('ssoGroupRequest'):
                    request_data = callback_params['ssoGroupRequest']
                elif callback_params.get('mailbox_email'):
                    request_data = {
                        'mailbox_email': callback_params.get('mailbox_email'),
                        'user_email': callback_params.get('user_email')
                    }
                
                notify_bot_approval_processed(
                    approval_id=approval_id,
                    status='approved',
                    result_message=result_message,
                    slack_context=callback_params.get('emailData', {}).get('slackContext', {}),
                    interaction_id=callback_params.get('interaction_id'),
                    approver=approver,
                    request_data=request_data
                )
        
        return True
        
    except Exception as e:
        print(f"❌ Error processing approval response: {e}")
        return False

def send_slack_confirmation(approval_id, status, approver, request_type):
    """Send confirmation message to Slack"""
    try:
        status_emoji = "✅" if status == "approved" else "❌"
        message = f"{status_emoji} Approval {approval_id} {status} by {approver} for {request_type}"
        
        slack_data = {
            'channel': SLACK_CHANNEL,
            'text': message,
            'username': 'IT Approval System'
        }
        
        req = urllib.request.Request(
            'https://slack.com/api/chat.postMessage',
            data=json.dumps(slack_data).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {SLACK_BOT_TOKEN}'
            }
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                print("📧 Confirmation sent to Slack")
                return True
            else:
                print(f"❌ Slack error: {result.get('error')}")
                return False
                
    except Exception as e:
        print(f"❌ Error sending Slack confirmation: {e}")
        return False

def send_execution_result_email(original_message_id, original_subject, requester_email, success, message):
    """Send email notification about execution result"""
    try:
        # Create email content based on actual result
        if success:
            subject = f"✅ Approved and Completed: {original_subject}"
            body = f"""Your request has been approved and successfully executed.

Result: {message}

Original Request: {original_subject}
Status: Completed Successfully

If you have any questions, please contact IT support.
"""
        else:
            subject = f"⚠️ Approved but Failed: {original_subject}"
            body = f"""Your request was approved but encountered an issue during execution.

Error: {message}

Original Request: {original_subject}
Status: Execution Failed

Please contact IT support for assistance.
"""
        
        # Queue email for sending
        print(f"📧 Execution result email queued for {requester_email}")
        
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
        if callback_params:
            # Check for direct user_email/mailbox_email (shared mailbox format)
            if 'user_email' in callback_params:
                users = callback_params['user_email']
            if 'mailbox_email' in callback_params:
                target = callback_params['mailbox_email']
            
            # Check for plan-based format (distribution list format)
            if 'plan' in callback_params:
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
                    target = ", ".join(targets)
        
        # Create Slack message with buttons
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 IT Approval Required"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Requested by:* {requester}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*For user:* {users}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Group:* {target}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Action:* Add to group"
                    }
                ]
            }
        ]
        
        # Add ticket info if available
        if ticket_number:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Ticket:* {ticket_number}" + (f" - <{ticket_url}|View Ticket>" if ticket_url else "")
                }
            })
        
        # Add details if available
        if details and details.strip():
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Details:*\n```{details}```"
                }
            })
        
        # Add action buttons
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Approve"
                    },
                    "style": "primary",
                    "action_id": f"approve_{approval_id}"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Deny"
                    },
                    "style": "danger",
                    "action_id": f"deny_{approval_id}"
                }
            ]
        })
        
        slack_data = {
            'channel': SLACK_CHANNEL,
            'blocks': blocks,
            'username': 'IT Approval System'
        }
        
        req = urllib.request.Request(
            'https://slack.com/api/chat.postMessage',
            data=json.dumps(slack_data).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {SLACK_BOT_TOKEN}'
            }
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                print(f"📧 Approval request sent to Slack: {approval_id}")
                return True
            else:
                print(f"❌ Slack error: {result.get('error')}")
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
    try:
        body = event.get('body', '')
        parsed_data = urllib.parse.parse_qs(body)
        
        if 'payload' in parsed_data:
            payload = json.loads(parsed_data['payload'][0])
            
            if payload.get('type') == 'block_actions':
                action = payload['actions'][0]['action_id']
                user = payload['user']['username']
                
                if action.startswith('approve_'):
                    approval_id = action.replace('approve_', '')
                    print(f"🔘 Button action: {action} by {user} - APPROVING")
                    
                    if process_approval_response(approval_id, 'APPROVE', user):
                        return {
                            'statusCode': 200,
                            'body': json.dumps({'text': f'✅ Approved by {user}'})
                        }
                    else:
                        return {
                            'statusCode': 500,
                            'body': json.dumps({'text': '❌ Error processing approval'})
                        }
                
                elif action.startswith('deny_'):
                    approval_id = action.replace('deny_', '')
                    print(f"🔘 Button action: {action} by {user} - DENYING")
                    
                    if process_approval_response(approval_id, 'DENY', user):
                        return {
                            'statusCode': 200,
                            'body': json.dumps({'text': f'❌ Denied by {user}'})
                        }
                    else:
                        return {
                            'statusCode': 500,
                            'body': json.dumps({'text': '❌ Error processing denial'})
                        }
        
        return {
            'statusCode': 200,
            'body': json.dumps({'text': 'OK'})
        }
        
    except Exception as e:
        print(f"❌ Error handling Slack interaction: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'text': 'Error processing request'})
        }

def lambda_handler(event, context):
    """Main Lambda handler"""
    
    print(f"Received event: {json.dumps(event)}")
    
    # Handle Slack webhook interactions FIRST
    if event.get('httpMethod') == 'POST' and 'body' in event:
        return handle_slack_interaction(event, context)
    
    # Handle different types of requests
    action = event.get('action', 'create_approval')
    
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
            approver=event.get('approver', 'system')
        )
        
        return {
            'statusCode': 200 if success else 500,
            'body': json.dumps({
                'success': success,
                'message': 'Processed successfully' if success else 'Processing failed'
            })
        }
    
    elif event.get('httpMethod') == 'POST':
        # Handle Slack webhook
        return handle_slack_interaction(event, context)
    
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Unknown action'})
        }
