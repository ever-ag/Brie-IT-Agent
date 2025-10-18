import json
import boto3
import urllib.parse
import uuid
from datetime import datetime

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
table = dynamodb.Table('it-actions')
interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

def log_to_conversation(interaction_id, timestamp, message, from_bot=True):
    """Log message to conversation history in dashboard"""
    if not interaction_id or not timestamp:
        print(f"⚠️ Cannot log to conversation: missing interaction_id or timestamp")
        return
    
    try:
        response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': int(timestamp)})
        if 'Item' not in response:
            print(f"⚠️ Conversation not found: {interaction_id}")
            return
        
        item = response['Item']
        history = json.loads(item.get('conversation_history', '[]'))
        
        history.append({
            'timestamp': datetime.utcnow().isoformat(),
            'message': message[:500],
            'from': 'bot' if from_bot else 'user'
        })
        
        interactions_table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': int(timestamp)},
            UpdateExpression='SET conversation_history = :hist, last_updated = :updated',
            ExpressionAttributeValues={
                ':hist': json.dumps(history),
                ':updated': datetime.utcnow().isoformat()
            }
        )
        print(f"✅ Logged to conversation {interaction_id}: {message[:50]}...")
    except Exception as e:
        print(f"❌ Error logging to conversation: {e}")

def lambda_handler(event, context):
    """Enhanced IT Approval System with task execution - fixed DynamoDB keys"""
    
    print(f"📥 Received event: {json.dumps(event)}")
    
    # Handle direct Lambda invocation (create_approval)
    if 'action' in event:
        return handle_direct_invocation(event)
    
    # Handle API Gateway event (Slack button interactions)
    if 'body' in event:
        return handle_slack_interaction(event)
    
    return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid request format'})}

def handle_direct_invocation(event):
    """Handle direct Lambda calls for creating approvals"""
    action = event.get('action')
    
    if action == 'create_approval':
        return create_approval(event)
    elif action == 'process_response':
        return process_approval_response(event)
    elif action == 'get_pending':
        return get_pending_approvals()
    else:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid action. Use: create_approval, process_response, or get_pending'})}

def handle_slack_interaction(event):
    """Handle Slack button interactions"""
    try:
        body = event['body']
        print(f"📄 Raw body: {body}")
        
        # Parse URL-encoded data
        parsed_data = urllib.parse.parse_qs(body)
        print(f"📋 Parsed data: {parsed_data}")
        
        if 'payload' not in parsed_data:
            return {'statusCode': 400, 'body': 'Missing payload'}
        
        # Parse JSON payload
        payload = json.loads(parsed_data['payload'][0])
        print(f"🎯 Slack payload: {payload}")
        
        if payload.get('type') == 'block_actions':
            return handle_button_action(payload)
        
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        print(f"❌ Error processing Slack interaction: {e}")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}

def handle_resolution_button(action_id, payload):
    """Handle resolution button clicks from IT support responses"""
    try:
        user = payload.get('user', {})
        username = user.get('username', 'Unknown')
        user_id = user.get('id', 'Unknown')
        
        print(f"🔧 Resolution button: {action_id} clicked by {username}")
        
        # Extract ticket info from button action_id if available
        action_parts = payload.get('actions', [{}])[0].get('action_id', '').split('_')
        ticket_id = action_parts[1] if len(action_parts) > 1 else None
        
        # Update dashboard status
        status = 'Resolved' if action_id == 'resolved' else 'In Progress'
        if ticket_id:
            update_dashboard_status(ticket_id, status, username)
        
        # Send appropriate response based on button clicked
        if action_id == 'resolved':
            send_resolution_response(user_id, "✅ Great! I'm glad I could help resolve your issue.")
        elif action_id == 'unresolved':
            send_resolution_response(user_id, "I understand the issue isn't fully resolved. Let me create a ticket for you to get additional help.")
        elif action_id == 'ticket':
            send_resolution_response(user_id, "I'll create a support ticket for you right away. You'll receive an email confirmation shortly.")
        
        return {'statusCode': 200, 'body': 'Resolution recorded'}
        
    except Exception as e:
        print(f"❌ Error handling resolution button: {e}")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}

def update_dashboard_status(ticket_id, status, username):
    """Update ticket status in dashboard system"""
    try:
        # Update DynamoDB table or whatever system tracks the dashboard
        response = table.update_item(
            Key={'ticket_id': ticket_id},
            UpdateExpression='SET ticket_status = :status, last_updated = :timestamp, updated_by = :user',
            ExpressionAttributeValues={
                ':status': status,
                ':timestamp': datetime.now().isoformat(),
                ':user': username
            }
        )
        print(f"📊 Dashboard updated: {ticket_id} -> {status}")
    except Exception as e:
        print(f"❌ Error updating dashboard: {e}")

def send_resolution_response(user_id, message):
    """Send response message to user after resolution button click"""
    import os
    import urllib3
    
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    if not bot_token:
        return
    
    http = urllib3.PoolManager()
    
    payload = {
        'channel': user_id,
        'text': message
    }
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            body=json.dumps(payload),
            headers=headers
        )
        print(f"Resolution response sent: {response.status}")
    except Exception as e:
        print(f"Failed to send resolution response: {e}")

def handle_button_action(payload):
    """Handle Slack button clicks"""
    try:
        actions = payload.get('actions', [])
        if not actions:
            return {'statusCode': 400, 'body': 'No actions found'}
        
        action = actions[0]
        action_id = action.get('action_id', '')
        user = payload.get('user', {})
        username = user.get('username', 'Unknown')
        
        print(f"🔘 Button action: {action_id} by {username}")
        
        # Handle resolution buttons (check if action_id starts with resolution keywords)
        if action_id.startswith('resolved_') or action_id.startswith('needhelp_') or action_id.startswith('ticket_'):
            # Extract the base action type
            base_action = action_id.split('_')[0]
            if base_action == 'needhelp':
                base_action = 'unresolved'
            print(f"🔀 Routing resolution button to it-helpdesk-bot: {action_id}")
            return handle_resolution_button(base_action, payload)
        
        # Extract approval ID from action_id (format: approve_XXXXX or deny_XXXXX)
        if '_' in action_id:
            action_type, approval_id = action_id.split('_', 1)
            
            if action_type == 'approve':
                return process_approval(approval_id, username, True)
            elif action_type == 'deny':
                return process_approval(approval_id, username, False)
        
        return {'statusCode': 400, 'body': 'Invalid action format'}
        
    except Exception as e:
        print(f"❌ Error handling button action: {e}")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}

def create_approval(event):
    """Create a new approval request"""
    try:
        print(f"🔧 Creating approval with event: {json.dumps(event)}")
        
        approval_id = str(uuid.uuid4())[:8]
        
        # Extract conversation tracking info
        email_data = event.get('emailData', {})
        slack_context = email_data.get('slackContext', {})
        interaction_id = email_data.get('interaction_id')
        
        # Store approval in DynamoDB using action_id as key
        approval_data = {
            'action_id': f"approval_{approval_id}",
            'approval_id': approval_id,
            'request_type': event.get('approvalType') or event.get('request_type', 'UNKNOWN'),
            'user_id': slack_context.get('user_id'),
            'user_name': slack_context.get('user_name'),
            'user_email': event.get('requester'),
            'group_name': event.get('ssoGroupRequest', {}).get('group_name') or event.get('group_name'),
            'details': event.get('details'),
            'requester': event.get('requester'),
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'interaction_id': interaction_id,
            'timestamp': slack_context.get('timestamp')
        }
        
        table.put_item(Item=approval_data)
        
        # Log approval request to conversation
        approval_msg = f"🚨 IT approval request created for {approval_data.get('request_type')}"
        log_to_conversation(interaction_id, slack_context.get('timestamp'), approval_msg, from_bot=True)
        
        # Send Slack approval message
        send_slack_approval(approval_data)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'approval_id': approval_id,
                'status': 'pending'
            })
        }
        
    except Exception as e:
        print(f"❌ Error creating approval: {e}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

def process_approval(approval_id, approver, approved):
    """Process approval/denial and execute tasks"""
    try:
        # Get approval data using action_id
        response = table.get_item(Key={'action_id': f"approval_{approval_id}"})
        if 'Item' not in response:
            return {'statusCode': 404, 'body': 'Approval not found'}
        
        approval_data = response['Item']
        
        # Update approval status
        approval_data['status'] = 'approved' if approved else 'denied'
        approval_data['approver'] = approver
        approval_data['processed_at'] = datetime.now().isoformat()
        
        table.put_item(Item=approval_data)
        
        print(f"✅ Approval {'approved' if approved else 'denied'}: {approval_id} by {approver}")
        
        # Log approval decision to conversation
        decision_msg = f"✅ IT approved your request" if approved else f"❌ IT denied your request"
        log_to_conversation(approval_data.get('interaction_id'), approval_data.get('timestamp'), decision_msg, from_bot=True)
        
        if approved:
            # Execute the actual task
            execute_approved_task(approval_data)
        else:
            # Handle denial
            handle_denial(approval_data)
        
        # Send confirmation to Slack
        send_slack_confirmation(approval_data, approved)
        print("📧 Confirmation sent to Slack")
        
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        print(f"❌ Error processing approval: {e}")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}

def execute_approved_task(approval_data):
    """Execute the approved task based on request type"""
    request_type = approval_data.get('request_type')
    
    if request_type == 'SSO_GROUP':
        execute_sso_task(approval_data)
    elif request_type == 'DISTRIBUTION_LIST':
        execute_dl_task(approval_data)
    elif request_type == 'SHARED_MAILBOX':
        execute_mailbox_task(approval_data)
    else:
        execute_general_task(approval_data)

def execute_sso_task(approval_data):
    """Execute SSO group addition"""
    try:
        user_email = approval_data.get('user_email')
        group_name = approval_data.get('group_name')
        user_id = approval_data.get('user_id')
        
        if not user_email or not group_name:
            print(f"❌ ERROR: Missing user_email or group_name")
            return
        
        # Call brie-ad-group-manager
        response = lambda_client.invoke(
            FunctionName='brie-ad-group-manager',
            Payload=json.dumps({
                'user_email': user_email,
                'group_name': group_name,
                'action': 'add',
                'emailData': {'source': 'it-helpdesk-bot'},
                'slackContext': {'channel': user_id}
            })
        )
        
        result = json.loads(response['Payload'].read())
        print(f"🔧 SSO task result: {result}")
        
        # Send completion message to user
        send_user_completion_message(approval_data, result)
        
    except Exception as e:
        print(f"❌ Error executing SSO task: {e}")

def execute_dl_task(approval_data):
    """Execute distribution list task"""
    try:
        user_email = approval_data.get('user_email')
        group_name = approval_data.get('group_name')
        user_id = approval_data.get('user_id')
        
        if not user_email or not group_name:
            print(f"❌ ERROR: Missing user_email or group_name")
            return
        
        # Call brie-ad-group-manager
        response = lambda_client.invoke(
            FunctionName='brie-ad-group-manager',
            Payload=json.dumps({
                'user_email': user_email,
                'group_name': group_name,
                'action': 'add',
                'emailData': {'source': 'it-helpdesk-bot'},
                'slackContext': {'channel': user_id}
            })
        )
        
        result = json.loads(response['Payload'].read())
        print(f"🔧 DL task result: {result}")
        
        # Send completion message to user
        send_user_completion_message(approval_data, result)
        
    except Exception as e:
        print(f"❌ Error executing DL task: {e}")

def execute_mailbox_task(approval_data):
    """Execute mailbox task"""
    send_user_completion_message(approval_data, {'success': True, 'message': 'Mailbox access granted'})

def execute_general_task(approval_data):
    """Execute general IT task"""
    send_user_completion_message(approval_data, {'success': True, 'message': 'IT request completed'})

def handle_denial(approval_data):
    """Handle denied requests"""
    send_user_denial_message(approval_data)

def send_slack_approval(approval_data):
    """Send approval request to Slack"""
    import os
    import urllib3
    
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    if not bot_token:
        return
    
    http = urllib3.PoolManager()
    
    approval_id = approval_data['approval_id']
    
    # Log IT channel message to conversation
    it_msg = f"🚨 IT Automation Approval Request sent to IT channel\nType: {approval_data.get('request_type')}\nDetails: {approval_data.get('details')}"
    log_to_conversation(approval_data.get('interaction_id'), approval_data.get('timestamp'), it_msg, from_bot=True)
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🚨 IT Automation Approval Request*\n\n*Type:* {approval_data.get('request_type')}\n*Details:* {approval_data.get('details')}\n*Requested by:* <mailto:{approval_data.get('requester')}|{approval_data.get('requester')}>"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": f"approve_{approval_id}"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny"},
                    "style": "danger",
                    "action_id": f"deny_{approval_id}"
                }
            ]
        }
    ]
    
    payload = {
        'channel': 'C09KB40PL9J',
        'text': '🚨 IT Automation Approval Request',
        'blocks': blocks
    }
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            body=json.dumps(payload),
            headers=headers
        )
        print(f"Slack approval sent: {response.status}")
    except Exception as e:
        print(f"Failed to send Slack approval: {e}")

def send_slack_confirmation(approval_data, approved):
    """Send confirmation message to Slack channel"""
    import os
    import urllib3
    
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    if not bot_token:
        return
    
    http = urllib3.PoolManager()
    
    status = "✅ approved" if approved else "❌ denied"
    message = f"{status} this request"
    
    # Log IT decision to conversation
    approver = approval_data.get('approver', 'IT')
    decision_msg = f"IT Staff ({approver}) {status} the request in IT channel"
    log_to_conversation(approval_data.get('interaction_id'), approval_data.get('timestamp'), decision_msg, from_bot=True)
    
    payload = {
        'channel': 'C09KB40PL9J',
        'text': message
    }
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            body=json.dumps(payload),
            headers=headers
        )
    except Exception as e:
        print(f"Failed to send confirmation: {e}")

def send_user_completion_message(approval_data, result):
    """Send completion message to user"""
    import os
    import urllib3
    
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    if not bot_token:
        return
    
    http = urllib3.PoolManager()
    
    user_id = approval_data.get('user_id')
    group_name = approval_data.get('group_name', 'requested resource')
    
    if result.get('success'):
        if 'already' in result.get('message', '').lower():
            message = f"✅ Good news! You already have access to {group_name}. No changes needed."
        else:
            message = f"✅ Request completed! You now have access to {group_name}."
    else:
        message = f"❌ There was an issue processing your {group_name} request. IT will follow up."
    
    # Log completion message to conversation
    log_to_conversation(approval_data.get('interaction_id'), approval_data.get('timestamp'), message, from_bot=True)
    
    payload = {
        'channel': user_id,
        'text': message
    }
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            body=json.dumps(payload),
            headers=headers
        )
        print(f"User completion message sent: {response.status}")
    except Exception as e:
        print(f"Failed to send user message: {e}")

def send_user_denial_message(approval_data):
    """Send denial message to user"""
    import os
    import urllib3
    
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    if not bot_token:
        return
    
    http = urllib3.PoolManager()
    
    user_id = approval_data.get('user_id')
    
    message = "❌ Your request was denied. IT will review and may create a ticket for further assistance."
    
    # Log denial message to conversation
    log_to_conversation(approval_data.get('interaction_id'), approval_data.get('timestamp'), message, from_bot=True)
    
    payload = {
        'channel': user_id,
        'text': message
    }
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = http.request(
            'POST',
            'https://slack.com/api/chat.postMessage',
            body=json.dumps(payload),
            headers=headers
        )
        print(f"User denial message sent: {response.status}")
    except Exception as e:
        print(f"Failed to send denial message: {e}")

def get_pending_approvals():
    """Get all pending approvals"""
    try:
        response = table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': 'pending'}
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'pending_approvals': response.get('Items', [])
            })
        }
        
    except Exception as e:
        print(f"❌ Error getting pending approvals: {e}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
