import json
import boto3
import time
import os
import urllib.request
from datetime import datetime

ssm = boto3.client('ssm')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('it-actions')  # Use existing table

BESPIN_INSTANCE_ID = "i-0dca7766c8de43f08"
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', 'SLACK_BOT_TOKEN')
IT_APPROVAL_CHANNEL = "C09KB40PL9J"

def send_slack_message(channel, text):
    """Send message to Slack channel"""
    try:
        print(f"🔍 Sending to channel: {channel}, token: {SLACK_BOT_TOKEN[:20]}...")
        url = 'https://slack.com/api/chat.postMessage'
        data = json.dumps({
            'channel': channel,
            'text': text,
            'as_user': True
        }).encode('utf-8')
        
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            print(f"📤 Slack API response: {result}")
            if not result.get('ok'):
                print(f"❌ Slack API error: {result.get('error')}")
            return result.get('ok', False)
    except Exception as e:
        print(f"❌ Error sending Slack message: {e}")
        return False

def search_similar_groups(search_term):
    """Search for AD groups with similar names"""
    try:
        ps_script = f"""
$ErrorActionPreference = "Stop"
try {{
    $searchTerm = "{search_term}"
    $groups = Get-ADGroup -Filter "Name -like '*$searchTerm*'" | Select-Object -First 10 Name
    $groups | ForEach-Object {{ Write-Output $_.Name }}
}} catch {{
    Write-Output "ERROR: $_"
    exit 1
}}
"""
        
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [ps_script]},
            TimeoutSeconds=30
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for completion
        for _ in range(10):
            time.sleep(2)
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=BESPIN_INSTANCE_ID
            )
            if result['Status'] in ['Success', 'Failed']:
                break
        
        output = result.get('StandardOutputContent', '').strip()
        
        if output and 'ERROR:' not in output:
            groups = [line.strip() for line in output.split('\n') if line.strip()]
            return groups
        
        return []
        
    except Exception as e:
        print(f"Error searching groups: {e}")
        return []

def lambda_handler(event, context):
    """Execute AD group add/remove operation"""
    try:
        print(f"Executing SSO group operation: {json.dumps(event)}")
        
        # Handle both direct invocation and callback formats
        if event.get('action') == 'execute':
            # Callback format from approval system
            params = event.get('params', {})
            sso_request = params.get('ssoGroupRequest', {})
            email_data = params.get('emailData', {})
            approval_info = {
                'interaction_id': params.get('interaction_id'),
                'interaction_timestamp': params.get('interaction_timestamp')
            }
            approval_id = event.get('approval_id', 'N/A')
        else:
            # Direct invocation format
            sso_request = event.get('ssoGroupRequest', {})
            email_data = event.get('emailData', {})
            approval_info = event.get('approvalInfo', {})
            approval_id = approval_info.get('approval_id', 'N/A')
        
        user_email = sso_request.get('user_email')
        group_name = sso_request.get('group_name')
        action = sso_request.get('action', 'add')
        requester = sso_request.get('requester')
        
        print(f"🔍 SSO Request Details:")
        print(f"   user_email: {user_email}")
        print(f"   group_name: {group_name}")
        print(f"   action: {action}")
        print(f"   requester: {requester}")
        
        if not user_email:
            error_msg = "ERROR: user_email is missing from SSO request"
            print(f"❌ {error_msg}")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': error_msg})
            }
        
        # Extract approval details
        approved_by = approval_info.get('approver', 'Unknown')
        
        # If approver not in approval_info, try to look it up from approval record
        if approved_by == 'Unknown' and approval_id != 'N/A':
            try:
                approvals_table = dynamodb.Table('it-approvals')
                approval_response = approvals_table.get_item(Key={'approval_id': approval_id})
                if 'Item' in approval_response:
                    approved_by = approval_response['Item'].get('approved_by', 'Unknown')
                    print(f"📝 Found approver from approval record: {approved_by}")
            except Exception as e:
                print(f"⚠️ Could not look up approver: {e}")
        
        approved_at = approval_info.get('timestamp', int(time.time()))
        
        # PowerShell script to add/remove user from AD group
        ps_command = 'Add-ADGroupMember' if action == 'add' else 'Remove-ADGroupMember'
        
        ps_script = f"""
$ErrorActionPreference = "Stop"

try {{
    # Get user and group
    $userEmail = "{user_email}"
    $user = Get-ADUser -Filter "EmailAddress -eq '$userEmail'"
    
    if (-not $user) {{
        # Try searching by alias (proxyAddresses)
        Write-Output "INFO: Primary email not found, searching aliases..."
        $user = Get-ADUser -Filter "proxyAddresses -like '*$userEmail*'" -Properties proxyAddresses
        
        if (-not $user) {{
            Write-Output "ERROR: User not found in AD with email or alias: $userEmail"
            exit 1
        }}
        
        Write-Output "INFO: Found user via alias: $userEmail"
    }}
    
    $group = Get-ADGroup -Filter "Name -eq '{group_name}'"
    
    if (-not $group) {{
        Write-Output "ERROR: Group not found in AD: {group_name}"
        exit 1
    }}
    
    # Check if user is already a member (for add operations)
    if ("{action}" -eq "add") {{
        $isMember = Get-ADGroupMember -Identity $group.DistinguishedName | Where-Object {{ $_.DistinguishedName -eq $user.DistinguishedName }}
        if ($isMember) {{
            Write-Output "INFO: User $userEmail is already a member of group '{group_name}'"
            exit 0
        }}
    }}
    
    # Execute operation
    {ps_command} -Identity $group.DistinguishedName -Members $user.DistinguishedName -ErrorAction Stop
    
    Write-Output "SUCCESS: User $userEmail {action}ed {'to' if action == 'add' else 'from'} group '{group_name}'"
    
}} catch {{
    Write-Output "ERROR: $_"
    exit 1
}}
"""
        
        # Execute on domain controller
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [ps_script]},
            TimeoutSeconds=30
        )
        
        command_id = response['Command']['CommandId']
        print(f"Execution command ID: {command_id}")
        
        # Wait for completion
        for _ in range(10):
            time.sleep(2)
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=BESPIN_INSTANCE_ID
            )
            
            if result['Status'] in ['Success', 'Failed']:
                break
        
        output = result.get('StandardOutputContent', '').strip()
        error_output = result.get('StandardErrorContent', '').strip()
        
        print(f"Execution output: {output}")
        
        # Check for already-a-member
        already_member = 'already a member' in output.lower()
        success = 'SUCCESS:' in output or already_member
        
        # Log to DynamoDB
        log_entry = {
            'action_id': f"sso_{approval_id}_{int(time.time())}",
            'action_type': f"sso_group_{action}",
            'details': {
                'user_email': user_email,
                'group_name': group_name,
                'action': action,
                'requester': requester,
                'success': success,
                'output': output,
                'approval_id': approval_id,
                'approved_by': approved_by,
                'approved_at': approved_at
            },
            'requester': requester,
            'status': 'completed' if success else 'failed',
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        table.put_item(Item=log_entry)
        
        # Update conversation in interactions table if we have the interaction_id
        interaction_id = approval_info.get('interaction_id')
        interaction_timestamp = approval_info.get('interaction_timestamp')
        
        # If not in approval_info, try to find it in tracking table
        if not interaction_id:
            try:
                print(f"🔍 Looking up interaction tracking for {user_email}")
                # Retry up to 3 times with delay for eventual consistency
                for attempt in range(3):
                    tracking_response = table.scan(
                        FilterExpression='action_type = :type AND user_email = :email',
                        ExpressionAttributeValues={
                            ':type': 'sso_interaction_tracking',
                            ':email': user_email
                        }
                    )
                    if tracking_response.get('Items'):
                        # Get the most recent tracking record
                        items = tracking_response['Items']
                        tracking = max(items, key=lambda x: int(x.get('timestamp', 0)))
                        interaction_id = tracking.get('interaction_id')
                        interaction_timestamp = tracking.get('interaction_timestamp')
                        print(f"✅ Found interaction tracking: {interaction_id}")
                        # Clean up tracking record
                        table.delete_item(Key={'action_id': tracking['action_id']})
                        break
                    elif attempt < 2:
                        print(f"⚠️ No tracking found, retrying... (attempt {attempt + 1})")
                        time.sleep(2)
                    else:
                        print(f"⚠️ No tracking record found for {user_email} after 3 attempts")
            except Exception as e:
                print(f"⚠️ Failed to lookup interaction tracking: {e}")
        
        if interaction_id and interaction_timestamp:
            try:
                interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')
                interactions_table.update_item(
                    Key={'interaction_id': interaction_id, 'timestamp': interaction_timestamp},
                    UpdateExpression='SET outcome = :outcome, awaiting_approval = :awaiting',
                    ExpressionAttributeValues={
                        ':outcome': 'Resolved - Approved' if success else 'Resolved - Failed',
                        ':awaiting': False
                    }
                )
                print(f"✅ Updated conversation {interaction_id} to {'Resolved - Approved' if success else 'Resolved - Failed'}")
            except Exception as e:
                print(f"⚠️ Failed to update conversation: {e}")
        
        # Check if this came from Slack - use message_id as fallback
        slack_context = email_data.get('slackContext')
        if not slack_context:
            # Fallback: check if message_id starts with 'slack_'
            message_id = email_data.get('messageId', '')
            if message_id.startswith('slack_'):
                # Extract channel from message_id: slack_CHANNEL_TIMESTAMP
                parts = message_id.split('_')
                channel = parts[1] if len(parts) > 1 else None
                user_name = user_email.split('@')[0] if user_email else 'User'
                slack_context = {'channel': channel, 'user_name': user_name}
        
        if slack_context:
            channel = slack_context.get('channel')
            user_name = slack_context.get('user_name', 'User')
            
            if success:
                if already_member:
                    # Already a member message
                    user_message = f"ℹ️ You're already a member of **{group_name}**.\n\nNo changes needed!"
                else:
                    # Successfully added message
                    user_message = f"✅ **Request Completed!**\n\nYou've been added to **{group_name}**.\n\nThe change has been applied to Active Directory."
                
                send_slack_message(channel, user_message)
                
                # Update conversation history
                if interaction_id and interaction_timestamp:
                    try:
                        response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': interaction_timestamp})
                        if 'Item' in response:
                            item = response['Item']
                            history = json.loads(item.get('conversation_history', '[]'))
                            
                            # Add approval message to history
                            approval_message = f"✅ {approved_by} approved this request"
                            history.append({
                                'timestamp': datetime.utcnow().isoformat(),
                                'message': approval_message,
                                'from': 'system'
                            })
                            
                            # Add completion message to history
                            history.append({
                                'timestamp': datetime.utcnow().isoformat(),
                                'message': user_message,
                                'from': 'bot'
                            })
                            
                            interactions_table.update_item(
                                Key={'interaction_id': interaction_id, 'timestamp': interaction_timestamp},
                                UpdateExpression='SET conversation_history = :history',
                                ExpressionAttributeValues={':history': json.dumps(history)}
                            )
                            print(f"✅ Updated conversation history with approval result")
                    except Exception as e:
                        print(f"⚠️ Failed to update conversation history: {e}")
                
                # Post to IT channel
                status = "Already a member" if already_member else "Added"
                it_message = f"✅ **Request Completed**\n\nUser: {user_email}\nGroup: {group_name}\nAction: {status}\nApproved by: {approved_by}"
                send_slack_message(IT_APPROVAL_CHANNEL, it_message)
                print(f"Slack notifications sent to user and IT channel")
            else:
                # Check if group not found and this is from IT Helpdesk bot
                source = email_data.get('source')
                group_not_found = 'Group not found in AD' in output
                
                if group_not_found and source == 'it-helpdesk-bot':
                    # Search for similar groups
                    print(f"🔍 Group '{group_name}' not found, searching for similar groups...")
                    similar_groups = search_similar_groups(group_name.split()[0])  # Search first word
                    
                    if similar_groups:
                        print(f"Found {len(similar_groups)} similar groups: {similar_groups}")
                        # Send interactive message with options
                        user_message = f"❓ **Group Not Found**\n\nI couldn't find a group named **{group_name}**.\n\nDid you mean one of these?\n\n" + "\n".join([f"• {g}" for g in similar_groups]) + "\n\nPlease reply with the exact group name you want."
                        send_slack_message(channel, user_message)
                        
                        # Store pending selection in DynamoDB for follow-up
                        pending_entry = {
                            'action_id': f"pending_{user_email}_{int(time.time())}",
                            'action_type': 'pending_group_selection',
                            'details': {
                                'user_email': user_email,
                                'original_group_name': group_name,
                                'similar_groups': similar_groups,
                                'action': action,
                                'requester': requester,
                                'channel': channel
                            },
                            'requester': requester,
                            'status': 'pending_selection',
                            'created_at': datetime.utcnow().isoformat()
                        }
                        table.put_item(Item=pending_entry)
                        
                        return {
                            'statusCode': 200,
                            'success': False,
                            'pending_selection': True,
                            'similar_groups': similar_groups,
                            'message': 'Group not found, similar groups returned'
                        }
                    else:
                        # No similar groups found
                        user_message = f"❌ **Group Not Found**\n\nI couldn't find any groups matching **{group_name}**.\n\nPlease contact IT for assistance."
                        send_slack_message(channel, user_message)
                else:
                    # Regular error message
                    user_message = f"❌ **Request Failed**\n\nUnable to add you to **{group_name}**.\n\nError: {output}\n\nPlease contact IT for assistance."
                    send_slack_message(channel, user_message)
                
                # Post to IT channel
                it_message = f"❌ **Request Failed**\n\nUser: {user_email}\nGroup: {group_name}\nError: {output}"
                send_slack_message(IT_APPROVAL_CHANNEL, it_message)
                print(f"Slack error notifications sent")
        
        return {
            'statusCode': 200,
            'success': success,
            'message': output if success else error_output,
            'ssoGroupRequest': sso_request,
            'emailData': email_data
        }
        
    except Exception as e:
        print(f"Error executing SSO group operation: {e}")
        return {
            'statusCode': 500,
            'success': False,
            'error': str(e)
        }
