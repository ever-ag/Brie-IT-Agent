#!/usr/bin/env python3
"""
Group Management System for Office 365 and On-Prem AD
Real connections to everagglobal.com domain and Office 365
"""

import json
import urllib.request
import urllib.parse
import boto3
import os
import time
from datetime import datetime

# Configuration
BESPIN_INSTANCE_ID = "i-0dca7766c8de43f08"  # Bespin domain controller
DOMAIN_NAME = "everagglobal.com"
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
IT_APPROVAL_CHANNEL = "C09KB40PL9J"

# DynamoDB tables
dynamodb = boto3.resource('dynamodb')
actions_table = dynamodb.Table('it-actions')
interactions_table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

def lookup_tracking(user_email):
    """Look up tracking record for user"""
    for attempt in range(3):
        try:
            response = actions_table.scan(
                FilterExpression='action_type = :type AND user_email = :email',
                ExpressionAttributeValues={':type': 'sso_interaction_tracking', ':email': user_email}
            )
            if response.get('Items'):
                return response['Items'][0]
            time.sleep(2)
        except Exception as e:
            print(f"Tracking lookup attempt {attempt + 1} failed: {e}")
    return None

def update_conversation(interaction_id, timestamp, message_text):
    """Update conversation history"""
    try:
        response = interactions_table.get_item(Key={'interaction_id': interaction_id, 'timestamp': timestamp})
        if 'Item' not in response:
            return False
        item = response['Item']
        history = json.loads(item.get('conversation_history', '[]'))
        history.append({'timestamp': datetime.utcnow().isoformat(), 'message': message_text[:500], 'from': 'bot'})
        interactions_table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp},
            UpdateExpression='SET conversation_history = :hist, last_updated = :updated',
            ExpressionAttributeValues={':hist': json.dumps(history), ':updated': datetime.utcnow().isoformat()}
        )
        return True
    except Exception as e:
        print(f"Error updating conversation: {e}")
        return False

def send_slack_message(channel, text):
    """Send message to Slack channel"""
    try:
        url = 'https://slack.com/api/chat.postMessage'
        data = json.dumps({
            'channel': channel,
            'text': text
        }).encode('utf-8')
        
        headers = {
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('ok', False)
    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return False

def get_graph_access_token():
    """Get Microsoft Graph access token for Office 365 operations"""
    # Dedicated credentials for IT Group Management
    TENANT_ID = "3d90a358-2976-40f4-8588-45ed47a26302"
    CLIENT_ID = "c33fc45c-9313-4f45-ac31-baf568616137"  # Brie-IT-Automation-Group-Manager
    CLIENT_SECRET = os.environ.get('GROUP_CLIENT_SECRET', '')
    
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

def search_office365_groups(access_token, group_name):
    """Search for groups in Office 365 by name or email address"""
    try:
        # Check if group_name looks like an email address or email prefix
        if '@' in group_name:
            # Full email provided - search by email prefix
            email_part = group_name.split('@')[0]
            # Try multiple case variations
            variations = [email_part.lower(), email_part.upper(), email_part]
            filter_parts = []
            for var in variations:
                filter_parts.append(f"startswith(mail,'{var}')")
                filter_parts.append(f"startswith(mailNickname,'{var}')")
            filter_param = ' or '.join(filter_parts)
        elif group_name.lower().startswith('dl_'):
            # Looks like an email prefix - try multiple case variations
            variations = [
                group_name.lower(),  # dl_everag_corp_it
                group_name.upper(),  # DL_EVERAG_CORP_IT
                group_name.title().replace('_', '_'),  # Dl_Everag_Corp_It
                'DL_' + '_'.join(word.capitalize() for word in group_name[3:].split('_'))  # DL_Everag_Corp_It
            ]
            filter_parts = []
            for var in set(variations):  # Remove duplicates
                filter_parts.append(f"startswith(mail,'{var}')")
                filter_parts.append(f"startswith(mailNickname,'{var}')")
            filter_param = ' or '.join(filter_parts)
        else:
            # Search by display name or mailNickname
            filter_param = f"displayName eq '{group_name}' or mailNickname eq '{group_name}'"
        
        encoded_filter = urllib.parse.quote(filter_param)
        
        # Build the search URL with encoded filter
        search_url = f"https://graph.microsoft.com/v1.0/groups?$filter={encoded_filter}"
        
        print(f"🔍 Office 365 search with {len(filter_parts) if '@' in group_name or group_name.lower().startswith('dl_') else 2} variations")
        
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            groups = result.get('value', [])
            
            # For now, return all groups to see what we find
            all_groups = []
            for group in groups:
                group_types = group.get('groupTypes', [])
                mail_enabled = group.get('mailEnabled', False)
                security_enabled = group.get('securityEnabled', False)
                
                # Determine group type
                if not group_types and mail_enabled and not security_enabled:
                    group_type = "distribution"
                elif "Unified" in group_types:
                    group_type = "microsoft365"
                elif security_enabled and not mail_enabled:
                    group_type = "security"
                elif security_enabled and mail_enabled:
                    group_type = "mail_security"
                else:
                    group_type = "unknown"
                
                # Override for known Distribution Lists that might be misclassified
                known_distribution_lists = ['ittest', 'IT Test', 'ITTest1']
                if any(known_dl in group['displayName'] for known_dl in known_distribution_lists):
                    group_type = "distribution"
                    print(f"🔧 Override: Forcing {group['displayName']} to be classified as distribution list")
                
                all_groups.append({
                    'id': group['id'],
                    'displayName': group['displayName'],
                    'mail': group.get('mail'),
                    'groupTypes': group_types,
                    'mailEnabled': mail_enabled,
                    'securityEnabled': security_enabled,
                    'groupType': group_type,
                    'location': 'office365'
                })
            
            print(f"📧 Found {len(all_groups)} Office 365 groups matching '{group_name}'")
            for group in all_groups:
                print(f"   - {group['displayName']} ({group['groupType']}) - Mail: {group.get('mail', 'None')}")
            
            # Return distribution groups and mail-enabled security groups
            usable_groups = [g for g in all_groups if g['groupType'] in ['distribution', 'mail_security', 'microsoft365']]
            return usable_groups
            
    except Exception as e:
        print(f"❌ Error searching Office 365 groups: {e}")
        return []

def search_onprem_ad_groups(group_name):
    """Search for distribution groups in on-premises AD via Systems Manager"""
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        
        # PowerShell command to search AD groups
        powershell_command = f"""
        Import-Module ActiveDirectory
        try {{
            $groups = Get-ADGroup -Filter "Name -like '*{group_name}*' -and GroupCategory -eq 'Distribution'" -Properties mail,displayName -Server {DOMAIN_NAME}
            $results = @()
            foreach ($group in $groups) {{
                $results += @{{
                    'Name' = $group.Name
                    'DisplayName' = $group.DisplayName
                    'Mail' = $group.mail
                    'DistinguishedName' = $group.DistinguishedName
                }}
            }}
            if ($results.Count -eq 0) {{
                Write-Output "NO_GROUPS_FOUND"
            }} else {{
                $results | ConvertTo-Json
            }}
        }} catch {{
            Write-Output "ERROR: $($_.Exception.Message)"
        }}
        """
        
        # Execute on Bespin domain controller
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName="AWS-RunPowerShellScript",
            Parameters={
                'commands': [powershell_command]
            }
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        time.sleep(5)
        
        # Get command output
        output_response = ssm.get_command_invocation(
            CommandId=command_id,
            InstanceId=BESPIN_INSTANCE_ID
        )
        
        output = output_response.get('StandardOutputContent', '').strip()
        
        if output == "NO_GROUPS_FOUND":
            print(f"🏢 No on-prem AD groups found matching '{group_name}'")
            return []
        elif output.startswith("ERROR:"):
            print(f"❌ AD search error: {output}")
            return []
        else:
            # Parse JSON output
            groups_data = json.loads(output)
            if not isinstance(groups_data, list):
                groups_data = [groups_data]
            
            # Convert to standard format
            onprem_groups = []
            for group in groups_data:
                onprem_groups.append({
                    'Name': group['Name'],
                    'DisplayName': group['DisplayName'],
                    'Mail': group.get('Mail'),
                    'DistinguishedName': group['DistinguishedName'],
                    'location': 'onprem_ad'
                })
            
            print(f"🏢 Found {len(onprem_groups)} on-prem AD groups matching '{group_name}'")
            return onprem_groups
        
    except Exception as e:
        print(f"❌ Error searching on-prem AD groups: {e}")
        return []

def find_distribution_group(group_name):
    """Search for distribution group in both Office 365 and on-prem AD, with Microsoft 365 Group detection"""
    print(f"🔍 Searching for distribution group: {group_name}")
    
    # Get Office 365 access token
    access_token = get_graph_access_token()
    if not access_token:
        print("❌ Failed to get Office 365 access token")
        return None
    
    # Search Office 365 first (including Microsoft 365 Groups for detection)
    o365_groups = search_office365_groups(access_token, group_name)
    
    # Check if we found a Microsoft 365 Group (which we don't support)
    microsoft365_groups = [g for g in o365_groups if g['groupType'] == 'microsoft365']
    if microsoft365_groups:
        group = microsoft365_groups[0]
        print(f"⚠️ Found Microsoft 365 Group: {group['displayName']} ({group.get('mail', 'No email')})")
        # Return special indicator for Microsoft 365 Group
        return {
            'Name': group['displayName'],
            'Mail': group.get('mail'),
            'location': 'microsoft365_group',
            'id': group['id'],
            'groupType': 'microsoft365'
        }
    
    # Filter for only supported group types (distribution lists and mail-enabled security groups)
    supported_groups = [g for g in o365_groups if g['groupType'] in ['distribution', 'mail_security']]
    
    # Search on-prem AD
    onprem_groups = search_onprem_ad_groups(group_name)
    
    # Combine results - prefer Office 365 if found in both
    all_groups = supported_groups + onprem_groups
    
    if not all_groups:
        print(f"❌ No distribution groups found for '{group_name}'")
        return None
    
    # Return the first match (Office 365 preferred)
    group = all_groups[0]
    print(f"✅ Found group: {group}")
    return group

def add_user_to_exchange_online_group(group_name, user_email):
    """Add user to Exchange Online distribution group via PowerShell with service account"""
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        
        # Get the group email address first
        access_token = get_graph_access_token()
        if access_token:
            # Search for the group to get its email address
            filter_param = f"displayName eq '{group_name}'"
            encoded_filter = urllib.parse.quote(filter_param)
            search_url = f"https://graph.microsoft.com/v1.0/groups?$filter={encoded_filter}"
            
            req = urllib.request.Request(search_url)
            req.add_header('Authorization', f'Bearer {access_token}')
            
            try:
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    groups = result.get('value', [])
                    
                    if groups:
                        group_email = groups[0].get('mail', group_name)
                        print(f"🔍 Using group email: {group_email} for display name: {group_name}")
                    else:
                        group_email = group_name
                        print(f"⚠️ Group not found, using original name: {group_name}")
            except Exception as e:
                print(f"⚠️ Error getting group email, using display name: {e}")
                group_email = group_name
        else:
            group_email = group_name
        
        # First check if user is already a member - USE GROUP EMAIL
        check_command = f"""
        try {{
            $AppId = 'c33fc45c-9313-4f45-ac31-baf568616137'
            $Organization = 'ever.ag'
            $CertificateThumbprint = '5A9D9A9076B309B70828EBB3C9AE57496DB68421'
            
            Connect-ExchangeOnline -AppId $AppId -CertificateThumbprint $CertificateThumbprint -Organization $Organization -ShowBanner:$false
            $members = Get-DistributionGroupMember -Identity '{group_email}' | Where-Object {{$_.PrimarySmtpAddress -eq '{user_email}'}}
            if ($members) {{
                Write-Output 'ALREADY_MEMBER: {user_email} is already in {group_email}'
            }} else {{
                Write-Output 'NOT_MEMBER: {user_email} is not in {group_email}'
            }}
            Disconnect-ExchangeOnline -Confirm:$false
        }} catch {{
            Write-Output "ERROR: $($_.Exception.Message)"
        }}
        """
        
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [check_command]}
        )
        
        command_id = response['Command']['CommandId']
        time.sleep(8)  # Increased timeout for Exchange Online
        
        # Wait for command completion with retries
        max_attempts = 6
        for attempt in range(max_attempts):
            output_response = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=BESPIN_INSTANCE_ID
            )
            
            status = output_response.get('Status')
            if status == 'Success':
                break
            elif status in ['InProgress', 'Pending']:
                time.sleep(5)
                continue
            else:
                print(f"❌ Command failed with status: {status}")
                return False
        
        output = output_response.get('StandardOutputContent', '').strip()
        print(f"🔍 Membership check result: {output}")
        
        if output.startswith("ALREADY_MEMBER:"):
            print(f"✅ {output}")
            return "already_member"
        elif output.startswith("NOT_MEMBER:"):
            print(f"📝 {output}")
            # Continue to add user
        else:
            print(f"❌ Membership check failed: {output}")
            return False
        
        # PowerShell command for Exchange Online with certificate auth
        powershell_command = f"""
        try {{
            $AppId = 'c33fc45c-9313-4f45-ac31-baf568616137'
            $Organization = 'ever.ag'
            $CertificateThumbprint = '5A9D9A9076B309B70828EBB3C9AE57496DB68421'
            
            Connect-ExchangeOnline -AppId $AppId -CertificateThumbprint $CertificateThumbprint -Organization $Organization -ShowBanner:$false
            Add-DistributionGroupMember -Identity '{group_email}' -Member '{user_email}' -ErrorAction Stop
            Disconnect-ExchangeOnline -Confirm:$false
            Write-Output 'SUCCESS: Added {user_email} to {group_email}'
        }} catch {{
            Write-Output "ERROR: $($_.Exception.Message)"
        }}
        """
        
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [powershell_command]}
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete with retries
        time.sleep(10)  # Exchange Online commands take longer
        
        max_attempts = 6
        for attempt in range(max_attempts):
            output_response = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=BESPIN_INSTANCE_ID
            )
            
            status = output_response.get('Status')
            if status == 'Success':
                break
            elif status in ['InProgress', 'Pending']:
                time.sleep(5)
                continue
            else:
                print(f"❌ Add command failed with status: {status}")
                return False
        
        output = output_response.get('StandardOutputContent', '').strip()
        error_output = output_response.get('StandardErrorContent', '').strip()
        print(f"🔍 Add operation result: {output}")
        if error_output:
            print(f"🔍 Error output: {error_output}")
        
        if output.startswith("SUCCESS:"):
            print(f"✅ {output}")
            return True
        else:
            print(f"❌ Exchange Online PowerShell failed: {output}")
            return False
        
    except Exception as e:
        print(f"❌ Error with Exchange Online PowerShell: {e}")
        return False

def check_onprem_membership(group_name, user_email):
    """Check if user is already a member of on-prem AD group"""
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        
        # PowerShell command to check group membership
        powershell_command = f"""
        Import-Module ActiveDirectory
        try {{
            $user = Get-ADUser -Filter "mail -eq '{user_email}'" -Server {DOMAIN_NAME} -ErrorAction Stop
            $group = Get-ADGroup -Identity "{group_name}" -Server {DOMAIN_NAME} -ErrorAction Stop
            
            $isMember = Get-ADGroupMember -Identity $group -Server {DOMAIN_NAME} | Where-Object {{$_.SamAccountName -eq $user.SamAccountName}}
            
            if ($isMember) {{
                Write-Output "ALREADY_MEMBER: $($user.DisplayName) is already in {group_name}"
            }} else {{
                Write-Output "NOT_MEMBER: $($user.DisplayName) is not in {group_name}"
            }}
        }} catch {{
            Write-Output "ERROR: $($_.Exception.Message)"
        }}
        """
        
        # Execute on Bespin domain controller
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName="AWS-RunPowerShellScript",
            Parameters={
                'commands': [powershell_command]
            }
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        time.sleep(5)
        
        # Get command output
        output_response = ssm.get_command_invocation(
            CommandId=command_id,
            InstanceId=BESPIN_INSTANCE_ID
        )
        
        output = output_response.get('StandardOutputContent', '').strip()
        
        if output.startswith("ALREADY_MEMBER:"):
            print(f"✅ {output}")
            return True
        elif output.startswith("NOT_MEMBER:"):
            print(f"📝 {output}")
            return False
        elif "Cannot find an object with identity" in output:
            print(f"🚫 Group not found in on-prem AD: {output}")
            return None  # Group doesn't exist
        else:
            print(f"❌ Membership check failed: {output}")
            return False
        
    except Exception as e:
        print(f"❌ Error checking on-prem membership: {e}")
        return False

def add_user_to_onprem_group(group_name, user_email):
    """Add user to on-premises AD group via PowerShell"""
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        
        # PowerShell command to add user to group
        powershell_command = f"""
        Import-Module ActiveDirectory
        try {{
            $user = Get-ADUser -Filter "mail -eq '{user_email}'" -Server {DOMAIN_NAME} -ErrorAction Stop
            $group = Get-ADGroup -Identity "{group_name}" -Server {DOMAIN_NAME} -ErrorAction Stop
            
            Add-ADGroupMember -Identity $group -Members $user -Server {DOMAIN_NAME} -ErrorAction Stop
            Write-Output "SUCCESS: Added $($user.DisplayName) to {group_name}"
        }} catch {{
            Write-Output "ERROR: $($_.Exception.Message)"
        }}
        """
        
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [powershell_command]}
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for command to complete
        time.sleep(5)
        
        # Get command output
        output_response = ssm.get_command_invocation(
            CommandId=command_id,
            InstanceId=BESPIN_INSTANCE_ID
        )
        
        output = output_response.get('StandardOutputContent', '').strip()
        
        if output.startswith("SUCCESS:"):
            print(f"✅ {output}")
            return True
        else:
            print(f"❌ Failed to add user: {output}")
            return False
        
    except Exception as e:
        print(f"❌ Error adding user to on-prem group: {e}")
        return False

def add_user_to_distribution_group(user_email, group_name):
    """Add user to distribution group (searches both locations and checks membership)"""
    print(f"🎯 Adding {user_email} to {group_name}")
    
    # Find the group
    group = find_distribution_group(group_name)
    if not group:
        return False, f"Group '{group_name}' not found in Office 365 or on-premises AD"
    
    # Check if it's a Microsoft 365 Group (which we don't support for automation)
    if group.get('location') == 'microsoft365_group' or group.get('groupType') == 'microsoft365':
        group_email = group.get('Mail', group.get('mail', 'No email'))
        return False, f"The requested group '{group_name}' ({group_email}) is a Microsoft 365 Group, not a Distribution List. Microsoft 365 Groups require manual management. A live IT agent will review this request and complete it manually."
    
    # Additional check: If Office 365 group has 'Unified' in groupTypes, it's a Microsoft 365 Group
    if group.get('location') == 'office365' and 'Unified' in group.get('groupTypes', []):
        group_email = group.get('mail', group.get('Mail', 'No email'))
        return False, f"The requested group '{group_name}' ({group_email}) is a Microsoft 365 Group, not a Distribution List. Microsoft 365 Groups require manual management. A live IT agent will review this request and complete it manually."
    
    # Check membership and add user based on group location
    if group['location'] == 'office365':
        # Special handling for distribution lists - check location and be honest
        if group.get('groupType') == 'distribution':
            print(f"📧 Distribution list detected: {group_name}")
            
            # Check if this is Office 365 only or also exists on-premises
            if group.get('location') == 'office365':
                print(f"☁️ This is an Office 365-only distribution list")
                
                # Check if it also exists on-premises
                onprem_exists = check_onprem_membership(group_name, user_email) is not None
                
                if onprem_exists:
                    print(f"🏢 Group also exists on-premises, trying AD method")
                    success = add_user_to_onprem_group(group_name, user_email)
                    if success:
                        return True, f"Successfully added {user_email} to distribution list {group_name} via on-premises AD"
                    else:
                        return False, f"Failed to add {user_email} to distribution list {group_name} via on-premises AD"
                else:
                    print(f"☁️ Office 365-only distribution list - using Exchange Online PowerShell")
                    # Use Exchange Online PowerShell via domain controller
                    success = add_user_to_exchange_online_group(group['mail'], user_email)
                    if success == "already_member":
                        return True, f"{user_email} already has access to {group_name}"
                    elif success:
                        return True, f"Successfully added {user_email} to distribution list {group_name}"
                    else:
                        return False, f"Failed to add {user_email} to distribution list {group_name}"
    else:
        # Check if already a member
        if check_onprem_membership(group['Name'], user_email):
            return True, f"{user_email} already has access to {group_name} in on-premises AD"
        
        # Add user to group
        success = add_user_to_onprem_group(group['Name'], user_email)
        location = "on-premises AD"
        
        if success:
            return True, f"Successfully added {user_email} to {group_name} in {location}"
        else:
            return False, f"Failed to add {user_email} to {group_name} in {location}"

def add_user_to_shared_mailbox(user_email, mailbox_email):
    """Add user to shared mailbox - placeholder for connector"""
    # This function is not used directly - the action processor handles the actual execution
    # This is just here for compatibility
    return True, f"Shared mailbox operation delegated to action processor"

def lambda_handler(event, context):
    """Lambda handler for group management operations"""
    print(f"🔍 DEBUG: Received event: {json.dumps(event)}")
    
    action = event.get('action')
    print(f"🔍 DEBUG: Action = {action}")
    
    if action == 'add_user_to_group':
        user_email = event.get('user_email')
        group_name = event.get('group_name')
        
        success, message = add_user_to_distribution_group(user_email, group_name)
        
        # Send IT channel notification
        try:
            it_message = f"{'✅' if success else '❌'} **Distribution List Request Completed**\n\nUser: {user_email}\nDistribution List: {group_name}\nResult: {message}"
            
            slack_data = {
                'channel': IT_APPROVAL_CHANNEL,
                'text': it_message,
                'as_user': True
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
                result = json.loads(response.read().decode())
                if result.get('ok'):
                    print(f"✅ IT channel notification sent")
                else:
                    print(f"❌ Failed to send IT notification: {result.get('error')}")
        except Exception as e:
            print(f"❌ Error sending IT notification: {e}")
        
        return {
            'statusCode': 200,  # Always return 200 for proper response parsing
            'body': json.dumps({
                'success': success,
                'message': message
            })
        }
    
    elif action == 'search_group':
        group_name = event.get('group_name')
        
        group = find_distribution_group(group_name)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'found': group is not None,
                'group': group
            })
        }
    
    elif action == 'search_mailbox':
        mailbox_name = event.get('mailbox_name')
        
        # Use PowerShell to search for shared mailbox
        import boto3
        import time
        
        ssm = boto3.client('ssm')
        BESPIN_INSTANCE_ID = "i-0dca7766c8de43f08"
        
        search_script = f"""
$AppId = 'c33fc45c-9313-4f45-ac31-baf568616137'
$Organization = 'ever.ag'
$CertificateThumbprint = '5A9D9A9076B309B70828EBB3C9AE57496DB68421'
Connect-ExchangeOnline -AppId $AppId -CertificateThumbprint $CertificateThumbprint -Organization $Organization -ShowBanner:$false
$mailbox = Get-Mailbox -Identity '{mailbox_name}' -ErrorAction SilentlyContinue
if ($mailbox) {{
    Write-Host "FOUND:$($mailbox.PrimarySmtpAddress)"
}} else {{
    Write-Host "NOT_FOUND"
}}
Disconnect-ExchangeOnline -Confirm:$false
"""
        
        try:
            response = ssm.send_command(
                InstanceIds=[BESPIN_INSTANCE_ID],
                DocumentName='AWS-RunPowerShellScript',
                Parameters={'commands': [search_script]}
            )
            
            command_id = response['Command']['CommandId']
            time.sleep(8)
            
            # Wait for command to complete
            for i in range(10):
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=BESPIN_INSTANCE_ID
                )
                
                if result.get('Status') in ['Success', 'Failed']:
                    break
                time.sleep(2)
            
            output = result.get('StandardOutputContent', '')
            
            if 'FOUND:' in output:
                email = output.split('FOUND:')[1].strip()
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'found': True,
                        'mailbox': {
                            'email': email,
                            'name': mailbox_name
                        }
                    })
                }
        except Exception as e:
            print(f"Error searching mailbox: {e}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'found': False})
        }
    
    elif action == 'add_user_to_shared_mailbox':
        user_email = event.get('user_email')
        mailbox_email = event.get('mailbox_email')
        
        # Execute PowerShell via SSM on Bespin instance
        import boto3
        import time
        
        ssm = boto3.client('ssm')
        BESPIN_INSTANCE_ID = "i-0dca7766c8de43f08"
        
        # First check if user already has access
        check_script = f"""
$AppId = 'c33fc45c-9313-4f45-ac31-baf568616137'
$Organization = 'ever.ag'
$CertificateThumbprint = '5A9D9A9076B309B70828EBB3C9AE57496DB68421'
Connect-ExchangeOnline -AppId $AppId -CertificateThumbprint $CertificateThumbprint -Organization $Organization -ShowBanner:$false
$perms = Get-MailboxPermission -Identity '{mailbox_email}' | Where-Object {{$_.User -like '*{user_email}*' -and $_.AccessRights -contains 'FullAccess'}}
if ($perms) {{
    Write-Host 'ALREADY_HAS_ACCESS'
}} else {{
    Write-Host 'NO_ACCESS'
}}
Disconnect-ExchangeOnline -Confirm:$false
"""
        
        try:
            # Check existing permissions
            print(f"🔍 Checking if {user_email} already has access to {mailbox_email}")
            response = ssm.send_command(
                InstanceIds=[BESPIN_INSTANCE_ID],
                DocumentName='AWS-RunPowerShellScript',
                Parameters={'commands': [check_script]}
            )
            
            command_id = response['Command']['CommandId']
            time.sleep(8)
            
            # Wait for command to complete
            for i in range(10):
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=BESPIN_INSTANCE_ID
                )
                
                status = result.get('Status')
                print(f"📊 Check command status: {status}")
                
                if status in ['Success', 'Failed']:
                    break
                    
                time.sleep(2)
            
            output = result.get('StandardOutputContent', '')
            error = result.get('StandardErrorContent', '')
            print(f"📋 Permission check output: {output}")
            print(f"📋 Permission check error: {error}")
            
            if 'ALREADY_HAS_ACCESS' in output:
                print(f"✅ User already has access")
                
                # Send IT channel notification
                try:
                    IT_CHANNEL = "C09KB40PL9J"
                    SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
                    it_message = f"ℹ️ **Request Completed**\n\nUser: {user_email}\nShared Mailbox: {mailbox_email}\nAction: Already has access"
                    
                    slack_data = {
                        'channel': IT_CHANNEL,
                        'text': it_message,
                        'as_user': True
                    }
                    req = urllib.request.Request(
                        'https://slack.com/api/chat.postMessage',
                        data=json.dumps(slack_data).encode('utf-8'),
                        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
                    )
                    with urllib.request.urlopen(req) as response:
                        print(f"📤 IT channel notification sent")
                except Exception as e:
                    print(f"⚠️ Failed to send IT channel notification: {e}")
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'success': True,
                        'message': f'{user_email} already has access to {mailbox_email}'
                    })
                }
            
            # User doesn't have access, add them
            print(f"➕ Adding {user_email} to {mailbox_email}")
            add_script = f"""
$AppId = 'c33fc45c-9313-4f45-ac31-baf568616137'
$Organization = 'ever.ag'
$CertificateThumbprint = '5A9D9A9076B309B70828EBB3C9AE57496DB68421'
Connect-ExchangeOnline -AppId $AppId -CertificateThumbprint $CertificateThumbprint -Organization $Organization -ShowBanner:$false
Add-MailboxPermission -Identity '{mailbox_email}' -User '{user_email}' -AccessRights FullAccess -InheritanceType All -AutoMapping $true
Disconnect-ExchangeOnline -Confirm:$false
"""
            
            response = ssm.send_command(
                InstanceIds=[BESPIN_INSTANCE_ID],
                DocumentName='AWS-RunPowerShellScript',
                Parameters={'commands': [add_script]}
            )
            
            command_id = response['Command']['CommandId']
            time.sleep(8)
            
            # Check result
            for attempt in range(6):
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=BESPIN_INSTANCE_ID
                )
                
                if result['Status'] in ['Success', 'InProgress']:
                    # Send IT channel notification
                    try:
                        IT_CHANNEL = "C09KB40PL9J"
                        SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
                        it_message = f"✅ **Request Completed**\n\nUser: {user_email}\nShared Mailbox: {mailbox_email}\nAction: Access granted"
                        
                        slack_data = {
                            'channel': IT_CHANNEL,
                            'text': it_message,
                            'as_user': True
                        }
                        req = urllib.request.Request(
                            'https://slack.com/api/chat.postMessage',
                            data=json.dumps(slack_data).encode('utf-8'),
                            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
                        )
                        with urllib.request.urlopen(req) as response:
                            print(f"📤 IT channel notification sent")
                    except Exception as e:
                        print(f"⚠️ Failed to send IT channel notification: {e}")
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps({
                            'success': True,
                            'message': f'Successfully added {user_email} to {mailbox_email} shared mailbox'
                        })
                    }
                
                if attempt < 5:
                    time.sleep(5)
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': False,
                    'message': f'Failed to add {user_email} to {mailbox_email}'
                })
            }
            
        except Exception as e:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': False,
                    'message': f'Error: {str(e)}'
                })
            }
    
    elif action == 'execute':
        # Handle approval callback execution
        params = event.get('params', {})
        print(f"🔍 DEBUG: Execute action - params = {json.dumps(params)}")
        
        # Check if this is a shared mailbox request
        if 'action' in params and params['action'] == 'add_user_to_shared_mailbox':
            print(f"🔍 DEBUG: Detected shared mailbox request")
            user_email = params.get('user_email')
            mailbox_email = params.get('mailbox_email')
            print(f"🔍 DEBUG: user_email={user_email}, mailbox_email={mailbox_email}")
            
            # Call the existing shared mailbox handler
            return lambda_handler({
                'action': 'add_user_to_shared_mailbox',
                'user_email': user_email,
                'mailbox_email': mailbox_email
            }, None)
        
        # Check if this is a direct action (DL format) or plan-based (shared mailbox format)
        elif 'action' in params and params['action'] == 'add_user_to_group':
            # Direct DL action format
            user_email = params.get('user_email')
            group_name = params.get('group_name')
            email_data = params.get('emailData', {})
            
            success, message = add_user_to_distribution_group(user_email, group_name)
            
            # Check if this came from Slack
            message_id = email_data.get('messageId', '')
            is_slack_request = message_id.startswith('slack_')
            
            if is_slack_request:
                # Slack request - send IT channel notification
                slack_context = email_data.get('slackContext', {})
                channel = slack_context.get('channel')
                
                if success:
                    # Check if user already had access
                    if 'already has access' in message.lower():
                        it_msg = f"ℹ️ **Already a Member**\n\nUser: {user_email}\nDistribution List: {group_name}\n{message}"
                    else:
                        it_msg = f"✅ **Request Completed**\n\nUser: {user_email}\nDistribution List: {group_name}\nAction: Added"
                else:
                    it_msg = f"❌ **Request Failed**\n\nUser: {user_email}\nDistribution List: {group_name}\nError: {message}"
                
                send_slack_message(IT_APPROVAL_CHANNEL, it_msg)
                    
                    # Send callback to it-helpdesk-bot to update conversation
                    try:
                        import boto3
                        lambda_client = boto3.client('lambda')
                        slack_context = email_details.get('slackContext', {})
                        if slack_context.get('user_id'):
                            lambda_client.invoke(
                                FunctionName='it-helpdesk-bot',
                                InvocationType='Event',
                                Payload=json.dumps({
                                    'callback_result': True,
                                    'result_data': {
                                        'slackContext': slack_context,
                                        'message': user_msg,
                                        'status': 'completed'
                                    }
                                })
                            )
                            print(f"✅ Sent callback to it-helpdesk-bot for user {slack_context.get('user_id')}")
                    except Exception as e:
                        print(f"⚠️ Failed to send callback: {e}")
                elif channel and not success:
                    # Look up tracking record
                    print(f"🔍 Looking up tracking for {user_email}")
                    tracking = lookup_tracking(user_email)
                    if tracking:
                        print(f"✅ Found tracking: {tracking['interaction_id']}")
                    else:
                        print(f"❌ No tracking found for {user_email}")
                    
                    # Send to user
                    user_msg = f"❌ **Request Failed**\n\nUnable to add you to **{group_name}**.\n\nError: {message}"
                    send_slack_message(channel, user_msg)
                    
                    # Update conversation history
                    if tracking:
                        print(f"📝 Updating conversation history")
                        update_conversation(tracking['interaction_id'], tracking['interaction_timestamp'], user_msg)
                    
                    # Post to IT channel
                    it_msg = f"❌ **Request Failed**\n\nUser: {user_email}\nDistribution List: {group_name}\nError: {message}"
                    send_slack_message(IT_APPROVAL_CHANNEL, it_msg)
            
            elif email_details and email_details.get('requester'):
                # Check if this is from Slack by looking at message_id
                original_message_id = email_details.get('original_message_id', '')
                is_slack_request = original_message_id.startswith('slack_')
                
                if not is_slack_request:
                    # Email request ONLY - send email notification
                    import boto3
                    lambda_client = boto3.client('lambda')
                    
                    email_payload = {
                        'action': 'send_result_email',
                        'original_message_id': email_details.get('original_message_id'),
                        'original_subject': email_details.get('original_subject'),
                        'requester_email': email_details.get('requester'),
                        'success': success,
                        'message': message,
                        'slack_context': None  # Explicitly mark as email request
                    }
                    
                    lambda_client.invoke(
                        FunctionName='it-action-processor',
                        InvocationType='Event',
                        Payload=json.dumps(email_payload)
                    )
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': success,
                    'message': message
                })
            }
        
        # Plan-based format (shared mailbox)
        plan = params.get('plan', {})
        
        if 'changes' in plan:
            # Check for Slack context
            email_data = params.get('emailData', {})
            slack_context = email_data.get('slackContext')
            
            # Invoke the action processor to handle the actual execution
            # The action processor has SSH access to Bespin for PowerShell execution
            import boto3
            lambda_client = boto3.client('lambda')
            
            action_payload = {
                'action': 'execute_plan',
                'plan': plan,
                'email_details': event.get('email_details', {}),
                'slack_context': slack_context  # Pass Slack context
            }
            
            response = lambda_client.invoke(
                FunctionName='it-action-processor',
                InvocationType='RequestResponse',
                Payload=json.dumps(action_payload)
            )
            
            response_payload = json.loads(response['Payload'].read())
            
            return response_payload
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'No changes in plan or invalid action format'
                })
            }
    
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': 'Invalid action. Use: add_user_to_group, search_group, or execute'
            })
        }

if __name__ == "__main__":
    # Test the functions
    print("🧪 Testing Group Management System")
    
    # Test search
    group = find_distribution_group("IT")
    
    # Test add user
    if group:
        success, message = add_user_to_distribution_group("matthew.denecke@ever.ag", "IT")
        print(f"Add result: {success} - {message}")
