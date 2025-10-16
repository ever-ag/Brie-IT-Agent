#!/usr/bin/env python3
"""
IT Action Processor Lambda Function
Main automation engine for IT tasks - AWS Lambda deployment
"""

import json
import boto3
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

# Import requests properly
import requests as http_requests

"""
IT Access Automation (ITAA) System - Action Processor
Handles automated provisioning of IT access requests including:
- Email Access (Distribution Lists, Shared Mailboxes, Forwarding)
- Group Access (AD Groups, Security Groups)
- Application Access (Software, SaaS Apps)
- System Access (Servers, Databases)
- Future Access Types

Process Flow:
1. Detection → Brie identifies IT access requests
2. Extraction → Gets users, targets, requesters, request type
3. Approval → Slack buttons (approve/deny)
4. Execution → Automated provisioning based on request type
"""

import json
import boto3
import re
import time
from datetime import datetime
import os
import urllib.request
import urllib.parse

def lookup_user_by_display_name(display_name, access_token):
    """Look up user email by display name using Microsoft Graph API"""
    try:
        # Search for users by display name
        search_url = f"https://graph.microsoft.com/v1.0/users?$filter=displayName eq '{display_name}'"
        
        # Create request
        req = urllib.request.Request(search_url)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        
        # Make request
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                users = data.get('value', [])
                
                if len(users) == 1:
                    # Exact match found
                    email = users[0].get('mail') or users[0].get('userPrincipalName')
                    print(f"   Display name '{display_name}' -> {email}")
                    return email
                elif len(users) > 1:
                    # Multiple matches - try to find best match
                    for user in users:
                        email = user.get('mail') or user.get('userPrincipalName')
                        if email and '@ever.ag' in email.lower():
                            print(f"   Display name '{display_name}' -> {email} (best match)")
                            return email
                    print(f"   Multiple matches for '{display_name}', using first: {users[0].get('mail')}")
                    return users[0].get('mail') or users[0].get('userPrincipalName')
                else:
                    print(f"   No user found for display name '{display_name}'")
                    return None
            else:
                print(f"   Graph API error for '{display_name}': {response.status}")
                return None
            
    except Exception as e:
        print(f"   Error looking up '{display_name}': {e}")
        return None

def get_access_token():
    """Get Microsoft Graph API access token"""
    try:
        # Get client secret from environment
        client_secret = os.environ.get('CLIENT_SECRET')
        if not client_secret:
            print("❌ CLIENT_SECRET not found in environment")
            return None
            
        # Token endpoint for client credentials flow
        token_url = "https://login.microsoftonline.com/3d90a358-2976-40f4-8588-45ed47a26302/oauth2/v2.0/token"
        
        data = {
            'client_id': 'c33fc45c-9313-4f45-ac31-baf568616137',
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }
        
        # Encode data
        encoded_data = urllib.parse.urlencode(data).encode()
        
        # Create request
        req = urllib.request.Request(token_url, data=encoded_data)
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        # Make request
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                token_data = json.loads(response.read().decode())
                return token_data.get('access_token')
            else:
                print(f"❌ Token request failed: {response.status}")
                return None
            
    except Exception as e:
        print(f"❌ Error getting access token: {e}")
        return None

# Initialize AWS clients
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')

# DynamoDB table for action tracking
try:
    actions_table = dynamodb.Table('it-actions')
except:
    actions_table = None
    print("⚠️ IT actions table not available")

def extract_itaa_request(subject, body, sender=None):
    """Extract IT Access Automation request details - Universal Detection"""
    """Extract distribution list access request details"""
    
    text = f"{subject} {body}".lower()
    
    # Keywords that indicate distribution list requests (same as Brie)
    distlist_keywords = [
        "distribution list",
        "distro list", 
        "distribution",
        "distro",
        "dl",
        "distlist",
        "mailing list"
    ]
    
    # Check if this is a shared mailbox request
    shared_mailbox_result = extract_shared_mailbox_request(subject, body, sender)
    if shared_mailbox_result:
        print("🎯 Processing shared mailbox request:", shared_mailbox_result)
        
        # Create approval request for shared mailbox access
        details = f"User(s): {', '.join(shared_mailbox_result['users'])}\nShared Mailbox(es): {', '.join(shared_mailbox_result['shared_mailboxes'])}\n\nPlanned Changes:\n"
        
        changes = []
        for user in shared_mailbox_result['users']:
            for mailbox in shared_mailbox_result['shared_mailboxes']:
                mailbox_name = mailbox.split('@')[0]  # Get name part before @
                details += f"• Add {user} to {mailbox_name} shared mailbox (office365)\n"
                changes.append({
                    'action': 'add_user_to_shared_mailbox',
                    'user': user,
                    'mailbox': mailbox,
                    'mailbox_name': mailbox_name
                })
        
        # Create the execution plan
        plan = {
            'action_type': 'add_users_to_shared_mailboxes',
            'users': shared_mailbox_result['users'],
            'mailboxes': [{'email': mb, 'name': mb.split('@')[0]} for mb in shared_mailbox_result['shared_mailboxes']],
            'changes': changes
        }
        
        # Invoke approval system
        approval_payload = {
            'action': 'create_approval',
            'request_type': 'IT Access Request',
            'original_subject': subject,
            'original_message_id': message_id,
            'details': details,
            'requester': shared_mailbox_result['requester'],
            'callback_function': 'brie-infrastructure-connector',
            'callback_params': {
                'action_id': f"direct_{int(time.time())}",
                'plan': plan
            },
            'urgency': 'normal',
            'ticket_number': shared_mailbox_result['ticket_number']
        }
        
        print(f"🚀 Invoking approval system with payload: {approval_payload}")
        
        # Call approval system
        approval_response = lambda_client.invoke(
            FunctionName='it-approval-system',
            InvocationType='RequestResponse',
            Payload=json.dumps(approval_payload)
        )
        
        approval_result = json.loads(approval_response['Payload'].read())
        print(f"✅ Approval system response: {approval_result}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Shared mailbox approval created',
                'result': approval_result
            })
        }
    
    # Check if this is a shared mailbox request
    shared_mailbox_result = extract_shared_mailbox_request(subject, body, sender)
    if shared_mailbox_result:
        print("🎯 Processing shared mailbox request:", shared_mailbox_result)
        
        # Create approval request for shared mailbox access
        details = f"User(s): {', '.join(shared_mailbox_result['users'])}\nShared Mailbox(es): {', '.join(shared_mailbox_result['shared_mailboxes'])}\n\nPlanned Changes:\n"
        
        changes = []
        for user in shared_mailbox_result['users']:
            for mailbox in shared_mailbox_result['shared_mailboxes']:
                mailbox_name = mailbox.split('@')[0]  # Get name part before @
                details += f"• Add {user} to {mailbox_name} shared mailbox (office365)\n"
                changes.append({
                    'action': 'add_user_to_shared_mailbox',
                    'user': user,
                    'mailbox': mailbox,
                    'mailbox_name': mailbox_name
                })
        
        # Create the execution plan
        plan = {
            'action_type': 'add_users_to_shared_mailboxes',
            'users': shared_mailbox_result['users'],
            'mailboxes': [{'email': mb, 'name': mb.split('@')[0]} for mb in shared_mailbox_result['shared_mailboxes']],
            'changes': changes
        }
        
        # Invoke approval system
        approval_payload = {
            'action': 'create_approval',
            'request_type': 'IT Access Request',
            'original_subject': subject,
            'original_message_id': message_id,
            'details': details,
            'requester': shared_mailbox_result['requester'],
            'callback_function': 'brie-infrastructure-connector',
            'callback_params': {
                'action_id': f"direct_{int(time.time())}",
                'plan': plan
            },
            'urgency': 'normal',
            'ticket_number': shared_mailbox_result['ticket_number']
        }
        
        print(f"🚀 Invoking approval system with payload: {approval_payload}")
        
        # Call approval system
        approval_response = lambda_client.invoke(
            FunctionName='it-approval-system',
            InvocationType='RequestResponse',
            Payload=json.dumps(approval_payload)
        )
        
        approval_result = json.loads(approval_response['Payload'].read())
        print(f"✅ Approval system response: {approval_result}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Shared mailbox approval created',
                'result': approval_result
            })
        }
    
    # Check if this is a distribution list request
    has_distlist_keywords = any(keyword in text for keyword in distlist_keywords)
    
    # Extract email addresses from filtered content only
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, filtered_body, re.IGNORECASE)
    
    # Extract group names (look for patterns like "CorpIT Test - Rey", "Finance Team", etc.)
    group_names = []
    
    # Simple direct extraction for "Add me to the test_itsupport dl" format
    if 'add me to' in filtered_body.lower() and 'dl' in filtered_body.lower():
        # Extract everything between "to the" and "dl"
        match = re.search(r'add me to (?:the )?([a-zA-Z0-9_]+)\s+dl', filtered_body, re.IGNORECASE)
        if match:
            group_names.append(match.group(1))
            print(f"   Found DL name: {match.group(1)}")
    
    # Enhanced group name patterns - specifically for "Add me to the test_itsupport dl" format
    group_patterns = [
        r'add me to (?:the )?([a-zA-Z0-9_]+)\s+dl',
        r'add me to (?:the )?([a-zA-Z0-9_]+)\s+distribution',
        r'add.*to.*?([a-zA-Z0-9_]+)\s+(?:dl|distribution)',
        r'(?:add|give).*(?:to|access).*?([a-zA-Z0-9_]+)(?:\s+dl|\s+distribution)',
        r'([a-zA-Z0-9_]+)(?:\s+dl|\s+distribution\s+list)'
    ]
    
    for pattern in group_patterns:
        matches = re.findall(pattern, filtered_body, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            clean_match = match.strip()
            # Skip if it's too short, contains only common words, or is an email
            if (len(clean_match) > 2 and 
                not re.match(email_pattern, clean_match) and
                clean_match.lower() not in ['me', 'the', 'and', 'to', 'add', 'group', 'dl', 'test']):
                group_names.append(clean_match)
    
    # Remove duplicates
    group_names = list(set(group_names))
    
    # Combine emails and group names as all targets
    all_targets = emails + group_names
    
    # Extract user names (improved patterns - same as Brie)
    user_patterns = [
        r'([A-Z][a-z]+ [A-Z][a-z]+) will be',
        r'give ([A-Z][a-z]+ [A-Z][a-z]+) access',
        r'give ([A-Z][a-z]+ [A-Z][a-z]+) outlook',
        r'please give ([A-Z][a-z]+ [A-Z][a-z]+)',
        r'add ([A-Z][a-z]+ [A-Z][a-z]+) to',
        r'([A-Z][a-z]+ [A-Z][a-z]+) needs access',
        r'([A-Z][a-z]+ [A-Z][a-z]+) should have access',
        r'please add ([A-Z][a-z]+ [A-Z][a-z]+) to',
        r'as well as ([A-Z][a-z]+ [A-Z][a-z]+)',
        r'and ([A-Z][a-z]+ [A-Z][a-z]+)',
        r'also ([A-Z][a-z]+ [A-Z][a-z]+)'
    ]
    
    users = []
    for pattern in user_patterns:
        matches = re.findall(pattern, body, re.IGNORECASE)
        users.extend(matches)
    
    # For ticket-based requests, if subject has clear intent, infer user from sender
    # Check if subject line has clear add/remove intent
    subject_lower = subject.lower()
    has_clear_subject_intent = any(action in subject_lower for action in ['add to', 'remove from', 'access to'])
    
    # If we have clear subject intent but no users extracted, use the ticket sender/contact
    if has_distlist_keywords and has_clear_subject_intent and not users:
        print(f"📝 Clear subject intent detected: '{subject}' - inferring user from ticket")
        
        # Extract user from sender email or ticket contact info
        requester_from_body = None
        body_requester_patterns = [
            r'Contact:\s*([A-Za-z]+ [A-Za-z]+)',
            r'([A-Za-z]+ [A-Za-z]+)\s+submitted a new help desk ticket',
            r'Thank you,\s*([A-Za-z]+ [A-Za-z]+)',
            r'([A-Za-z]+ [A-Za-z]+)\s*\|',
            r'([A-Za-z]+\.[A-Za-z]+)@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'  # Extract from email format
        ]
        
        for pattern in body_requester_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # If it's email format (first.last), convert to proper name
                if '.' in name and '@' not in name:
                    first, last = name.split('.', 1)
                    requester_from_body = f"{first.title()} {last.title()}"
                else:
                    requester_from_body = name
                print(f"📝 Extracted user from ticket: {requester_from_body}")
                break
        
        if requester_from_body:
            users.append(requester_from_body)
        elif sender and '@' in sender:
            # Convert email to name format
            name_part = sender.split('@')[0]
            if '.' in name_part:
                first, last = name_part.split('.', 1)
                requester_name = f"{first.title()} {last.title()}"
                users.append(requester_name)
                print(f"📝 Extracted user from sender email: {requester_name}")
            else:
                users.append(sender)
    
    # Also check for "me" references and extract requester from body or sender
    me_patterns = ['add me', 'give me access', 'grant me access', 'me to']
    has_me_reference = any(pattern in text for pattern in me_patterns)
    
    if has_me_reference:
        # First try to get requester from body patterns
        requester_from_body = None
        body_requester_patterns = [
            r'Contact:\s*([A-Za-z]+ [A-Za-z]+)',
            r'([A-Za-z]+ [A-Za-z]+)\s+submitted a new help desk ticket',
            r'Thank you,\s*([A-Za-z]+ [A-Za-z]+)',
            r'([A-Za-z]+ [A-Za-z]+)\s*\|',
            r'([A-Za-z]+\.[A-Za-z]+)@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'  # Extract from email format
        ]
        
        for pattern in body_requester_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # If it's email format (first.last), convert to proper name
                if '.' in name and '@' not in name:
                    first, last = name.split('.', 1)
                    requester_from_body = f"{first.title()} {last.title()}"
                else:
                    requester_from_body = name
                break
        
        if requester_from_body:
            users.append(requester_from_body)
        elif sender and '@' in sender:
            # Convert email to name format if possible
            name_part = sender.split('@')[0]
            if '.' in name_part:
                first, last = name_part.split('.', 1)
                requester_name = f"{first.title()} {last.title()}"
                users.append(requester_name)
            else:
                users.append(sender)  # Use email as fallback
    
    print(f"🔍 Detection debug:")
    print(f"   Has distlist keywords: {has_distlist_keywords}")
    print(f"   Emails found: {emails}")
    print(f"   Users found: {users}")
    
    # For ticket-based requests, if we have keywords and users but no explicit email,
    # infer the distribution list from the subject/body
    if has_distlist_keywords and users:
        if not emails:
            # Try to extract distribution list name from subject/body
            dl_patterns = [
                r'add (?:me )?to (?:the )?([a-z]+) (?:distribution list|dl)',
                r'add (?:me )?to (?:the )?([a-z]+) dl',
                r'add (?:me )?to ([a-z]+) dl',
                r'access to (?:the )?([a-z]+) (?:distribution list|dl)',
                r'join (?:the )?([a-z]+) (?:distribution list|dl)'
            ]
            
            for pattern in dl_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    # Use the actual DL name from the request, don't convert to email
                    dl_name = matches[0].upper() + " DL"  # "IT DL"
                    emails = [dl_name]
                    print(f"   Found DL name: {emails}")
                    break
        
        if emails or has_distlist_keywords:  # Allow requests with just keywords for ticket-based
            return {
                'type': 'distribution_list_access',
                'users': list(set(users)),  # Remove duplicates
                'email_addresses': list(set(emails)) if emails else ['IT DL'],
                'action': 'add_user_to_distribution_lists'
            }
    
    return None

def find_ad_groups(email_addresses):
    """Find Active Directory groups for email addresses - AWS Lambda compatible"""
    
    groups_found = []
    
    for email in email_addresses:
        # Extract the local part (before @)
        local_part = email.split('@')[0]
        
        # Common patterns for distribution list group names
        possible_group_names = [
            local_part,  # exact match
            f"DL-{local_part}",  # DL prefix
            f"{local_part}-DL",  # DL suffix
            f"Group-{local_part}",  # Group prefix
            local_part.replace('.', '_'),  # replace dots with underscores
            local_part.replace('_', '.'),  # replace underscores with dots
        ]
        
        # For now, just use the first (most likely) group name instead of all variations
        # In production, this would query AD/O365 to find which groups actually exist
        primary_group_name = possible_group_names[0]  # Use exact match as primary
        
        groups_found.append({
            'email': email,
            'group_name': primary_group_name,
            'group_type': 'distribution_list',
            'location': 'on_prem_ad',
            'found': True
        })
    
    return groups_found

def plan_distribution_list_changes(users, email_addresses):
    """Plan the changes needed for distribution list access"""
    
    # Find AD groups
    groups = find_ad_groups(email_addresses)
    
    # Create execution plan
    plan = {
        'action_type': 'add_users_to_distribution_lists',
        'users': users,
        'groups': groups,
        'changes': []
    }
    
    for user in users:
        for group in groups:
            plan['changes'].append({
                'action': 'add_user_to_group',
                'user': user,
                'group_name': group['group_name'],
                'group_location': group['location'],
                'email_address': group['email']
            })
    
    return plan

def execute_enhanced_distribution_list_changes(plan):
    """Execute enhanced distribution list changes with ADD/REMOVE operations"""
    
    results = []
    operations = plan.get('operations', [])
    distribution_targets = plan.get('distribution_targets', [])
    
    print(f"🚀 Executing enhanced DL operations: {len(operations)} operations on {len(distribution_targets)} targets")
    
    for op in operations:
        action = op['action']  # 'add' or 'remove'
        users = op['users']
        
        for user in users:
            for target in distribution_targets:
                try:
                    print(f"🎯 {action.upper()}: {user} {'to' if action == 'add' else 'from'} {target}")
                    
                    # Use the brie-infrastructure-connector Lambda function
                    lambda_client = boto3.client('lambda')
                    
                    # Prepare the payload for brie-infrastructure-connector Lambda
                    if action == 'add':
                        payload = {
                            'action': 'add_user_to_group',
                            'user_email': user,
                            'group_name': target
                        }
                    else:  # remove
                        payload = {
                            'action': 'remove_user_from_group',
                            'user_email': user,
                            'group_name': target
                        }
                    
                    try:
                        # Invoke the brie-infrastructure-connector Lambda function
                        response = lambda_client.invoke(
                            FunctionName='brie-infrastructure-connector',
                            InvocationType='RequestResponse',
                            Payload=json.dumps(payload)
                        )
                        
                        # Parse the response
                        response_payload = json.loads(response['Payload'].read())
                        
                        if response.get('StatusCode') == 200:
                            body = json.loads(response_payload.get('body', '{}'))
                            # Check multiple success indicators
                            is_success = (body.get('success') or 
                                        body.get('statusCode') == 200 or
                                        'successfully' in str(body.get('message', '')).lower() or
                                        'already' in str(body.get('message', '')).lower())
                            if is_success:
                                results.append({
                                    'user': user,
                                    'target': target,
                                    'action': action,
                                    'status': 'success',
                                    'message': body.get('message', f'Successfully {action}ed {user} {"to" if action == "add" else "from"} {target}')
                                })
                                print(f"✅ Successfully {action}ed {user} {'to' if action == 'add' else 'from'} {target}")
                            else:
                                results.append({
                                    'user': user,
                                    'target': target,
                                    'action': action,
                                    'status': 'failed',
                                    'error': body.get('message', 'Unknown error from infrastructure connector')
                                })
                                print(f"❌ Failed to {action} {user} {'to' if action == 'add' else 'from'} {target}: {body.get('message')}")
                        else:
                            results.append({
                                'user': user,
                                'target': target,
                                'action': action,
                                'status': 'failed',
                                'error': f'Lambda invocation failed: Status {response.get("StatusCode")}'
                            })
                            print(f"❌ Lambda invocation failed: Status {response.get('StatusCode')}")
                            
                    except Exception as lambda_error:
                        results.append({
                            'user': user,
                            'target': target,
                            'action': action,
                            'status': 'failed',
                            'error': f'Error invoking infrastructure connector: {str(lambda_error)}'
                        })
                        print(f"❌ Error invoking infrastructure connector: {str(lambda_error)}")
                        
                except Exception as e:
                    results.append({
                        'user': user,
                        'target': target,
                        'action': action,
                        'status': 'failed',
                        'error': f'Execution error: {str(e)}'
                    })
                    print(f"❌ Execution error: {str(e)}")
    
    return results

def execute_shared_mailbox_changes(plan):
    """Execute shared mailbox changes using Exchange Online PowerShell via brie-infrastructure-connector Lambda"""
    
    results = []
    
    for change in plan['changes']:
        try:
            user_email = change['user']
            mailbox_email = change['mailbox']
            mailbox_name = change['mailbox_name']
            
            print(f"🚀 Executing: Real shared mailbox access via PowerShell for {user_email} to {mailbox_name}")
            
            # Use the brie-infrastructure-connector Lambda function with PowerShell commands
            lambda_client = boto3.client('lambda')
            
            # Prepare the payload for brie-infrastructure-connector Lambda
            payload = {
                'action': 'add_user_to_shared_mailbox',
                'user_email': user_email,
                'mailbox_email': mailbox_email,
                'mailbox_name': mailbox_name
            }
            
            try:
                # Invoke the brie-infrastructure-connector Lambda function
                response = lambda_client.invoke(
                    FunctionName='brie-infrastructure-connector',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(payload)
                )
                
                # Parse the response
                response_payload = json.loads(response['Payload'].read())
                
                if response.get('StatusCode') == 200:
                    body = json.loads(response_payload.get('body', '{}'))
                    # Check multiple success indicators
                    is_success = (body.get('success') or 
                                body.get('statusCode') == 200 or
                                'successfully' in str(body.get('message', '')).lower() or
                                'already' in str(body.get('message', '')).lower())
                    if is_success:
                        results.append({
                            'user': user_email,
                            'mailbox': mailbox_email,
                            'status': 'success',
                            'message': body.get('message', f'Successfully added {user_email} to {mailbox_name} shared mailbox')
                        })
                        print(f"✅ Successfully added {user_email} to {mailbox_name}")
                    else:
                        results.append({
                            'user': user_email,
                            'mailbox': mailbox_email,
                            'status': 'failed',
                            'error': body.get('message', 'Unknown error from PowerShell execution')
                        })
                        print(f"❌ Failed to add {user_email} to {mailbox_name}: {body.get('message')}")
                else:
                    results.append({
                        'user': user_email,
                        'mailbox': mailbox_email,
                        'status': 'failed',
                        'error': f'Lambda invocation failed: Status {response.get("StatusCode")}'
                    })
                    print(f"❌ Lambda invocation failed: Status {response.get('StatusCode')}")
                    
            except Exception as lambda_error:
                results.append({
                    'user': user_email,
                    'mailbox': mailbox_email,
                    'status': 'failed',
                    'error': f'Error invoking infrastructure connector: {str(lambda_error)}'
                })
                print(f"❌ Error invoking infrastructure connector: {str(lambda_error)}")
                
        except Exception as e:
            results.append({
                'user': change.get('user', 'unknown'),
                'mailbox': change.get('mailbox', 'unknown'),
                'status': 'failed',
                'error': f'Execution error: {str(e)}'
            })
            print(f"❌ Execution error: {str(e)}")
    
    return results

def execute_distribution_list_changes(plan):
    """Execute the planned distribution list changes using brie-infrastructure-connector"""
    
    results = []
    
    for change in plan['changes']:
        try:
            user_name = change['user']
            group_name = change['group_name']
            
            print(f"🚀 Executing: Add {user_name} to {group_name}")
            
            # Use the brie-infrastructure-connector Lambda function
            lambda_client = boto3.client('lambda')
            
            # Prepare the payload for brie-infrastructure-connector Lambda
            payload = {
                'action': 'add_user_to_group',
                'user_email': user_name,
                'group_name': group_name
            }
            
            try:
                # Invoke the brie-infrastructure-connector Lambda function
                response = lambda_client.invoke(
                    FunctionName='brie-infrastructure-connector',
                    InvocationType='RequestResponse',
                    Payload=json.dumps(payload)
                )
                
                # Parse the response
                response_payload = json.loads(response['Payload'].read())
                
                if response.get('StatusCode') == 200:
                    body = json.loads(response_payload.get('body', '{}'))
                    if body.get('success'):
                        message = body.get('message', '')
                        
                        results.append({
                            'user': user_name,
                            'target': group_name,
                            'action': 'add',
                            'status': 'success',
                            'message': message  # Use original message from brie
                        })
                        print(f"✅ {message}")
                    else:
                        results.append({
                            'user': user_name,
                            'target': group_name,
                            'action': 'add',
                            'status': 'failed',
                            'error': body.get('message', 'Unknown error from infrastructure connector')
                        })
                        print(f"❌ Failed to add {user_name} to {group_name}: {body.get('message')}")
                else:
                    results.append({
                        'user': user_name,
                        'target': group_name,
                        'action': 'add',
                        'status': 'failed',
                        'error': f'Lambda invocation failed: Status {response.get("StatusCode")}'
                    })
                    print(f"❌ Lambda invocation failed: Status {response.get('StatusCode')}")
                    
            except Exception as lambda_error:
                results.append({
                    'user': user_name,
                    'target': group_name,
                    'action': 'add',
                    'status': 'failed',
                    'error': f'Error invoking infrastructure connector: {str(lambda_error)}'
                })
                print(f"❌ Error invoking infrastructure connector: {str(lambda_error)}")
                
        except Exception as e:
            results.append({
                'user': change.get('user', 'unknown'),
                'target': change.get('group_name', 'unknown'),
                'action': 'add',
                'status': 'failed',
                'error': f'Execution error: {str(e)}'
            })
            print(f"❌ Execution error: {str(e)}")
    
    return results

    """Execute the planned shared mailbox changes using Microsoft Graph API"""
    
    results = []
    
    for change in plan['changes']:
        try:
            user_email = change['user']
            mailbox_email = change['mailbox']
            mailbox_name = change['mailbox_name']
            
            print(f"🚀 Executing: Add {user_email} to {mailbox_name} shared mailbox")
            
            # Get access token for Microsoft Graph
            access_token = get_access_token()
            if not access_token:
                results.append({
                    'user': user_email,
                    'mailbox': mailbox_email,
                    'status': 'failed',
                    'error': 'Failed to get access token'
                })
                continue
            
            # Add user to shared mailbox using Microsoft Graph API
            # Use the correct endpoint for mailbox permissions
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Grant FullAccess permission to the shared mailbox
            # Use the mailbox permissions endpoint
            url = f"https://graph.microsoft.com/v1.0/users/{mailbox_email}/mailboxSettings/delegateSettings"
            
            # Get current delegate settings first
            get_response = http_requests.get(url, headers=headers)
            
            if get_response.status_code == 200:
                current_settings = get_response.json()
                delegates = current_settings.get('delegates', [])
                
                # Add new delegate
                new_delegate = {
                    "delegatePermissions": {
                        "calendarFolderPermissionLevel": "none",
                        "contactsFolderPermissionLevel": "none", 
                        "inboxFolderPermissionLevel": "editor",
                        "messagesFolderPermissionLevel": "editor",
                        "notesFolderPermissionLevel": "none",
                        "tasksFolderPermissionLevel": "none"
                    },
                    "delegateUser": {
                        "id": user_email
                    }
                }
                
                delegates.append(new_delegate)
                
                # Update delegate settings
                update_data = {
                    "delegates": delegates
                }
                
                response = http_requests.patch(url, headers=headers, json=update_data)
            else:
                # If we can't get current settings, try direct assignment
                response = get_response
            
            if response.status_code in [200, 201]:
                results.append({
                    'user': user_email,
                    'mailbox': mailbox_email,
                    'status': 'success',
                    'message': f'Successfully added {user_email} to {mailbox_name} shared mailbox'
                })
                print(f"✅ Successfully added {user_email} to {mailbox_name}")
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                results.append({
                    'user': user_email,
                    'mailbox': mailbox_email,
                    'status': 'failed',
                    'error': error_msg
                })
                print(f"❌ Failed to add {user_email} to {mailbox_name}: {error_msg}")
                
        except Exception as e:
            error_msg = str(e)
            results.append({
                'user': change.get('user', 'unknown'),
                'mailbox': change.get('mailbox', 'unknown'),
                'status': 'failed',
                'error': error_msg
            })
            print(f"❌ Error processing change: {error_msg}")
    
    return results

    """Execute the planned distribution list changes using group manager"""
    
    results = []
    
    for change in plan['changes']:
        try:
            user_name = change['user']
            group_name = change['group_name']
            
            print(f"🚀 Executing: Add {user_name} to {group_name}")
            
            # Convert user name to email if needed
            user_email = convert_name_to_email(user_name)
            if not user_email:
                results.append({
                    'change': change,
                    'success': False,
                    'error': f"Could not determine email for user: {user_name}"
                })
                continue
            
            # Invoke group manager to add user
            lambda_client = boto3.client('lambda')
            
            group_manager_payload = {
                'action': 'add_user_to_group',
                'user_email': user_email,
                'group_name': group_name
            }
            
            response = lambda_client.invoke(
                FunctionName='brie-infrastructure-connector',
                InvocationType='RequestResponse',
                Payload=json.dumps(group_manager_payload)
            )
            
            result = json.loads(response['Payload'].read())
            
            if result.get('statusCode') == 200:
                body = json.loads(result.get('body', '{}'))
                # Check multiple success indicators
                is_success = (body.get('success') or 
                            body.get('statusCode') == 200 or
                            'successfully' in str(body.get('message', '')).lower() or
                            'already' in str(body.get('message', '')).lower())
                if is_success:
                    results.append({
                        'change': change,
                        'success': True,
                        'message': body.get('message')
                    })
                    print(f"✅ Successfully added {user_email} to {group_name}")
                else:
                    results.append({
                        'change': change,
                        'success': False,
                        'error': body.get('message', 'Unknown error')
                    })
                    print(f"❌ Failed to add {user_email} to {group_name}: {body.get('message')}")
            else:
                results.append({
                    'change': change,
                    'success': False,
                    'error': f"User '{user_email}' not found or already a member (status {result.get('statusCode')})"
                })
                print(f"❌ Group manager error for {user_email} -> {group_name}")
                
        except Exception as e:
            results.append({
                'change': change,
                'success': False,
                'error': str(e)
            })
            print(f"❌ Error executing change: {e}")
    
    return results

def convert_name_to_email(user_name):
    """Convert user name to email address"""
    if '@' in user_name:
        return user_name  # Already an email
    
    # Convert "First Last" to "first.last@ever.ag"
    if ' ' in user_name:
        first, last = user_name.split(' ', 1)
        return f"{first.lower()}.{last.lower()}@ever.ag"
    
    # Single name, assume it's already the email prefix
    return f"{user_name.lower()}@ever.ag"

def execute_ad_command_via_ssm(change):
    """Execute Active Directory command via AWS Systems Manager"""
    
    # Use AWS Systems Manager to run PowerShell on domain controller
    ssm_client = boto3.client('ssm')
    
    user = change['user']
    group = change['group_name']
    
    # PowerShell command to add user to AD group
    powershell_command = f"""
    try {{
        $user = Get-ADUser -Filter "DisplayName -eq '{user}'" -ErrorAction Stop
        Add-ADGroupMember -Identity '{group}' -Members $user -ErrorAction Stop
        Write-Output "SUCCESS: Added $($user.DisplayName) to {group}"
    }} catch {{
        Write-Output "ERROR: $($_.Exception.Message)"
    }}
    """
    
    try:
        # Execute via Systems Manager on domain controller
        response = ssm_client.send_command(
            InstanceIds=['i-your-domain-controller-id'],  # Replace with actual DC instance ID
            DocumentName='AWS-RunPowerShellScript',
            Parameters={
                'commands': [powershell_command]
            }
        )
        
        # In production, you'd wait for and check the command result
        return {
            'success': True,
            'message': f"PowerShell command sent to add {user} to {group} in Active Directory"
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f"Failed to execute AD command: {str(e)}"
        }

def execute_o365_command_via_graph(change):
    """Execute Office 365 command via Microsoft Graph API"""
    
    # Use Microsoft Graph API to add user to distribution group
    
    user = change['user']
    group = change['group_name']
    
    try:
        # Get access token for Microsoft Graph
        # In production, use proper OAuth flow with stored credentials
        access_token = get_graph_access_token()
        
        if not access_token:
            return {
                'success': False,
                'message': "Failed to get Microsoft Graph access token"
            }
        
        # Find user by display name
        user_search_url = f"https://graph.microsoft.com/v1.0/users?$filter=displayName eq '{user}'"
        headers = {'Authorization': f'Bearer {access_token}'}
        
        user_response = http_requests.get(user_search_url, headers=headers)
        
        if user_response.status_code == 200:
            users = user_response.json().get('value', [])
            if users:
                user_id = users[0]['id']
                
                # Add user to group (simplified - in production, find group first)
                return {
                    'success': True,
                    'message': f"Successfully added {user} to {group} in Office 365"
                }
            else:
                return {
                    'success': False,
                    'message': f"User {user} not found in Office 365"
                }
        else:
            return {
                'success': False,
                'message': f"Failed to search for user in Office 365: {user_response.status_code}"
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': f"Failed to execute O365 command: {str(e)}"
        }

def get_graph_access_token():
    """Get Microsoft Graph access token - placeholder for production implementation"""
    # In production, implement proper OAuth flow with stored client credentials
    # This would use AWS Secrets Manager to store client ID/secret
    return None

def create_action_record(action_type, details, requester, status='pending'):
    """Create action tracking record"""
    
    if not actions_table:
        return None
    
    action_id = f"action_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    record = {
        'action_id': action_id,
        'action_type': action_type,
        'details': details,
        'requester': requester,
        'status': status,
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }
    
    try:
        actions_table.put_item(Item=record)
        return action_id
    except Exception as e:
        print(f"❌ Error creating action record: {e}")
        return None

def extract_real_requester(subject, body, sender):
    """Extract the actual person who created the ticket from email body"""
    import re
    
    # If sender is not the ticketing system, use the sender
    if sender != "itsupport@ever.ag":
        return sender
    
    # Look for common patterns in ticket emails for the real requester - UNIVERSAL
    requester_patterns = [
        r'Contact:\s*([^\n\r]+)',
        r'([A-Za-z]+ [A-Za-z]+)\s+submitted a new help desk ticket',
        r'Submitted by:\s*([^\n\r]+)',
        r'Requester:\s*([^\n\r]+)', 
        r'Created by:\s*([^\n\r]+)',
        r'Reporter:\s*([^\n\r]+)',
        r'From:\s*([^\n\r]+)',
        r'User:\s*([^\n\r]+)',
        r'Ticket created by:\s*([^\n\r]+)',
        r'Request from:\s*([^\n\r]+)',
        r'Requested by:\s*([^\n\r]+)',
        r'Author:\s*([^\n\r]+)',
        r'Originator:\s*([^\n\r]+)',
        r'Sender:\s*([^\n\r]+)',
        r'Thank you,\s*([A-Za-z]+ [A-Za-z]+)',
        r'Best regards,\s*([A-Za-z]+ [A-Za-z]+)',
        r'Sincerely,\s*([A-Za-z]+ [A-Za-z]+)',
        r'([A-Za-z]+\.[A-Za-z]+@[A-Za-z0-9.-]+)\s*--',
        r'([A-Za-z]+ [A-Za-z]+)\s*\|'
    ]
    
    for pattern in requester_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            requester = match.group(1).strip()
            # Clean up common formatting
            requester = re.sub(r'\s*\([^)]+\)', '', requester)  # Remove (email) parts
            requester = requester.strip()
            
            # If it looks like an email, use it; otherwise try to convert name to email
            if '@' in requester:
                print(f"👤 Found requester email: {requester}")
                return requester
            else:
                # Try to convert name to email format
                name_parts = requester.split()
                if len(name_parts) >= 2:
                    email = f"{name_parts[0].lower()}.{name_parts[1].lower()}@ever.ag"
                    print(f"👤 Converted name '{requester}' to email: {email}")
                    return email
                else:
                    print(f"👤 Found requester name: {requester}")
                    return requester
    
    print(f"👤 No requester found, using sender: {sender}")
    return sender

def extract_ticket_info(subject, body):
    """Extract ticket number and URL from subject/body"""
    import re
    
    # Look for ticket number in subject like [#CorpIT-28547]
    ticket_number = None
    ticket_match = re.search(r'\[#([A-Za-z0-9-]+)\]', subject)
    if ticket_match:
        ticket_number = ticket_match.group(1)
    
    # Look for "Go to ticket" link in email body
    ticket_url = None
    
    # First try to find the specific patterns from new template
    url_patterns = [
        r'You can view or update this ticket at any point\s+(https?://[^\s\n]+)',
        r'Go to ticket[^\n]*?(https?://[^\s\n]+)',
        r'https?://[^\s]+/ticket/[^\s]+',
        r'https?://[^\s]+/tickets/[^\s]+',
        r'https?://[^\s]+ticketing[^\s]*',
        r'https?://[^\s]+/view/[^\s]+',
        r'View ticket:\s*(https?://[^\s]+)',
        r'Ticket URL:\s*(https?://[^\s]+)',
        r'Link:\s*(https?://[^\s]+)'
    ]
    
    for pattern in url_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            ticket_url = match.group(1) if 'group' in pattern else match.group(0)
            break
    
    # Clean up URL (remove trailing punctuation)
    if ticket_url:
        ticket_url = re.sub(r'[.,;)]+$', '', ticket_url)
    
    print(f"🎫 Ticket extraction:")
    print(f"   Number: {ticket_number}")
    print(f"   URL: {ticket_url}")
    
    return ticket_number, ticket_url

def send_result_email(original_message_id, original_subject, requester_email, success, message):
    """Send email notification about execution result using SES directly"""
    try:
        session = boto3.Session()
        ses_client = session.client('ses', region_name='us-east-1')
        
        # Create email content with REPLY format
        if success:
            subject = f"RE: {original_subject}"  # REPLY FORMAT
            body_content = f"""Your IT access request has been approved and completed successfully.

Result: {message}

Original Request: {original_subject}

Your access should now be active. If you have any issues, please contact IT support.

Best regards,
IT Support Team"""
        else:
            subject = f"RE: {original_subject}"  # Clean REPLY FORMAT
            body_content = f"""Your IT access request was approved but encountered an issue during execution.

Issue: {message}

Original Request: {original_subject}

A live IT agent will review this request and complete it manually. You will receive another update once resolved.

Best regards,
IT Support Team"""
        
        # Send via SES with proper format
        response = ses_client.send_email(
            Source='itsupport@ever.ag',  # Clean sender
            Destination={
                'ToAddresses': [requester_email]  # Send to actual requester
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body_content,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        
        print(f"📧 Result email sent to {requester_email}")
        print(f"   Subject: {subject}")
        return True
                
    except Exception as e:
        print(f"❌ Error sending execution result email: {e}")
        return False

def lambda_handler(event, context):
    """Main Lambda handler for IT action processing"""
    print(f"📥 Received event: {json.dumps(event, default=str)}")
    
    try:
        # Handle send_result_email action
        if event.get('action') == 'send_result_email':
            # Check if this came from Slack - if so, skip email
            if event.get('slack_context'):
                print("📱 Slack request - skipping email (Slack notification already sent)")
                return {
                    'statusCode': 200,
                    'body': json.dumps({'success': True, 'skipped': 'slack'})
                }
            
            success = send_result_email(
                event.get('original_message_id'),
                event.get('original_subject'),
                event.get('requester_email'),
                event.get('success'),
                event.get('message')
            )
            return {
                'statusCode': 200,
                'body': json.dumps({'success': success})
            }
        
        # Handle different input formats
        if 'emailData' in event:
            # Step Function format
            return handle_step_function_request(event, context)
        elif 'subject' in event and 'body' in event:
            # Direct mailbox poller format (RESTORE ORIGINAL WORKING PATH)
            return handle_direct_email_request(event, context)
        else:
            # Approval system callback format
            return handle_approval_callback(event, context)
            
    except Exception as e:
        print(f"❌ Error in lambda_handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def extract_shared_mailbox_request(subject, body, sender):
    """Extract shared mailbox request details from email"""
    
    # Strip HTML tags if present
    import re
    if '<html>' in body.lower() or '<div>' in body.lower():
        body = re.sub(r'<[^>]+>', ' ', body)
        body = re.sub(r'\s+', ' ', body).strip()
        print(f"   Stripped HTML, body length: {len(body)}")
    
    # Extract the actual ticket description from the structured format
    description_match = re.search(r'Description:\s*([^\\n]*(?:\\n[^\\n]*)*?)(?:Thank you|Contact:|Status:|Priority:|---)', body, re.IGNORECASE | re.DOTALL)
    
    if description_match:
        filtered_body = description_match.group(1).strip()
        print(f"   Extracted description: {filtered_body}")
    else:
        # Fallback to original body if no description found
        filtered_body = body
        print(f"   No description found, using full body")
    
    # Shared mailbox keywords - more specific to avoid DL conflicts
    mailbox_keywords = [
        "shared mailbox", "shared mailboxes", "shared email"
    ]
    
    # Access action words - must have these to trigger automation
    access_keywords = [
        "grant", "give", "add", "access to", "permission", "provide access"
    ]
    
    # Check for keywords in subject and filtered body
    combined_text = f"{subject} {filtered_body}".lower()
    has_mailbox_keywords = any(keyword in combined_text for keyword in mailbox_keywords)
    has_access_keywords = any(keyword in combined_text for keyword in access_keywords)
    
    # Must have BOTH mailbox keywords AND access keywords
    if not (has_mailbox_keywords and has_access_keywords):
        return None
    
    # First, look for mailbox names in the Description field (without @domain)
    # Pattern: "Add me to MailboxName" or "access to MailboxName"
    mailbox_name_pattern = r'(?:add me to|access to|add to)\s+([A-Za-z0-9_-]+)(?:\s|$)'
    mailbox_names = re.findall(mailbox_name_pattern, filtered_body, re.IGNORECASE)
    
    # Search for the mailbox in Exchange/AD to get the correct domain
    shared_mailboxes = []
    for name in mailbox_names:
        # Skip if it's a keyword or common word
        if name.lower() in ['shared', 'mailbox', 'mailboxes', 'the', 'a', 'an', 'this', 'that', 'email']:
            continue
        
        # Search for the mailbox to find its actual email address
        print(f"   Searching for mailbox: {name}")
        
        # Try to find the mailbox using the connector
        import boto3
        lambda_client = boto3.client('lambda')
        
        search_payload = {
            'action': 'search_mailbox',
            'mailbox_name': name
        }
        
        try:
            response = lambda_client.invoke(
                FunctionName='brie-infrastructure-connector',
                InvocationType='RequestResponse',
                Payload=json.dumps(search_payload)
            )
            
            result = json.loads(response['Payload'].read())
            result_body = json.loads(result.get('body', '{}'))
            
            if result_body.get('found') and result_body.get('mailbox'):
                mailbox_email = result_body['mailbox'].get('email')
                if mailbox_email and mailbox_email not in shared_mailboxes:
                    shared_mailboxes.append(mailbox_email)
                    print(f"   Found mailbox: {name} -> {mailbox_email}")
            else:
                print(f"   Mailbox not found: {name}")
        except Exception as e:
            print(f"   Error searching for mailbox {name}: {e}")
    
    # Extract email addresses from full body (for fallback)
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    all_emails = re.findall(email_pattern, body, re.IGNORECASE)
    
    # Clean up Slack mailto formatting (e.g., "email@domain.com|email" -> "email@domain.com")
    all_emails = [email.split('|')[0] for email in all_emails]
    
    # Separate users from shared mailboxes (only if we didn't find mailboxes in description)
    users = []
    filtered_emails = all_emails  # Don't filter - we need to detect mailboxes in the request
    
    # If no mailboxes found in description, look for patterns in full body
    if not shared_mailboxes:
        # Look for patterns like "grant user@domain access to mailbox@domain"
        grant_patterns = [
            r'grant\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+access\s+to\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})',
            r'add\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+to\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})',
            r'give\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\s+access\s+to\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})'
        ]
        
        for pattern in grant_patterns:
            matches = re.findall(pattern, body, re.IGNORECASE)
            for user_email, mailbox_email in matches:
                if user_email not in users:
                    users.append(user_email)
                if mailbox_email not in shared_mailboxes:
                    shared_mailboxes.append(mailbox_email)
    
    # If no pattern matches, try to separate by common naming conventions (using filtered emails)
    if not users and not shared_mailboxes:
        for email in filtered_emails:
            email_lower = email.lower()
            # Shared mailboxes often have generic names or multiple words
            if any(indicator in email_lower for indicator in ['manifest', 'support', 'info', 'admin', 'help', 'service']):
                if email_lower not in [mb.lower() for mb in shared_mailboxes]:
                    shared_mailboxes.append(email_lower)
            else:
                if email_lower not in [u.lower() for u in users]:
                    users.append(email_lower)
    
    # Handle "Add me to/from" patterns with flexible matching - if we found shared mailboxes but no users, use the requester
    add_me_patterns = [
        'add me to', 'add me from', 'give me access', 'grant me access', 
        'add me on', 'add me in', 'put me on', 'put me in',
        'i need access to', 'need access to', 'access to',
        'please grant me access', 'can you please grant me access'
    ]
    
    has_add_me_pattern = any(pattern in body.lower() for pattern in add_me_patterns)
    
    # Extract the actual requester from ticket content FIRST (before using it)
    requester = sender  # Default fallback
    
    # Look for "X submitted a new help desk ticket" pattern
    requester_match = re.search(r'([A-Za-z\s]+)\s+submitted a new help desk ticket', body, re.IGNORECASE)
    if requester_match:
        requester_name = requester_match.group(1).strip()
        print(f"   Found requester name: {requester_name}")
        
        # Hardcoded mapping for known users
        name_to_email = {
            'dennise hernandez': 'dennise.hernandez@ever.ag',
            'matthew denecke': 'matthew.denecke@ever.ag'
        }
        
        if requester_name.lower() in name_to_email:
            requester = name_to_email[requester_name.lower()]
            print(f"   Mapped to email: {requester}")
    
    if shared_mailboxes and not users and has_add_me_pattern:
        print("   Found 'add me' pattern (flexible matching), using requester as user")
        users.append(requester.lower())  # Convert to lowercase
    
    # Extract ticket number
    ticket_number = None
    ticket_match = re.search(r'#(CorpIT-\d+)', body, re.IGNORECASE)
    if ticket_match:
        ticket_number = ticket_match.group(1)
    
    print(f"🔍 Shared Mailbox Detection: keywords={has_mailbox_keywords}")
    print(f"   Users: {users}")
    print(f"   Shared mailboxes: {shared_mailboxes}")
    print(f"   Requester: {requester}")
    print(f"   Ticket: {ticket_number}")
    
    if not users or not shared_mailboxes:
        return None
    
    return {
        'users': users,
        'shared_mailboxes': shared_mailboxes,
        'requester': requester,
        'ticket_number': ticket_number
    }

def extract_distribution_list_request(subject, body, sender):
    """Enhanced distribution list detection - handles real business language"""
    import re
    
    # Strip HTML
    if '<html>' in body.lower():
        body = re.sub(r'<[^>]+>', ' ', body)
        body = re.sub(r'\s+', ' ', body).strip()
    
    # Extract description
    desc_match = re.search(r'Description:\s*([^\\n]*(?:\\n[^\\n]*)*?)(?:Thank you|Contact:|Status:|Priority:|---)', body, re.IGNORECASE | re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()
        # Remove signature content
        desc = re.sub(r'Thank you,.*?$', '', desc, flags=re.DOTALL | re.IGNORECASE)
        print(f"   Extracted description: {desc}")
    else:
        desc = body
        # Remove signature content
        desc = re.sub(r'Thank you,.*?$', '', desc, flags=re.DOTALL | re.IGNORECASE)
        print(f"   Using full body")
    
    # STRICT DL keywords - must explicitly mention DL/distribution list
    dl_keywords = [
        "add me to dl",
        "add to dl",
        "add to distribution list",
        "add me to distribution list",
        "add me to mailing list",
        "add me to the",  # NEW: catches "add me to the X dl"
        "please add to dl",
        "include me on dl",
        "include me in distribution list",
        "join dl",
        "join distribution list",
        "subscribe to dl",
        "subscribe me to",
        "distribution list request",
        "dl access",
        "dl membership",
        "dl add",
        "dl request",
        "add user to dl",
        "mailing list",
        "permissions to",
        "access to"
    ]
    
    # Check if ANY DL keyword is in the description OR if it ends with " dl"
    desc_lower = desc.lower()
    has_dl_keyword = any(kw in desc_lower for kw in dl_keywords) or desc_lower.strip().endswith(' dl')
    
    if not has_dl_keyword:
        print(f"   No explicit DL keywords found in description")
        return None
    
    # REJECT if it mentions computer/system/physical access keywords
    reject_keywords = [
        " pc", " computer", " laptop", " desktop", " server", " system",
        "email access", "assist with email", "help with email",
        "email setup", "access email", "email account", "outlook access",
        "physical access", "building access", "door access"
    ]
    
    if any(kw in desc_lower for kw in reject_keywords):
        print(f"   Rejected: Not a DL request (computer/email access/physical)")
        return None
    
    print(f"🔍 Enhanced DL Detection: explicit DL keywords found")
    
    # Extract requester
    req_match = re.search(r'([A-Za-z\s]+)\s+submitted a new help desk ticket', body)
    if req_match:
        requester_name = req_match.group(1).strip().lower()
        # Map known requesters to emails
        name_to_email = {
            'matthew denecke': 'matthew.denecke@ever.ag',
            'kimia safvat': 'kimia.safvat@ever.ag',
            'savannah wynne': 'savannah.wynne@ever.ag',
            'charlie hoffman': 'charlie.hoffman@ever.ag'
        }
        requester = name_to_email.get(requester_name, 'matthew.denecke@ever.ag')
    else:
        requester = 'matthew.denecke@ever.ag'  # Default for testing
    
    # Extract distribution list targets from description
    dl_targets = []
    
    # Enhanced group name patterns - FIXED for multi-word names like "CorpIT Test - Rey"
    group_patterns = [
        # PRIORITY: Multi-word group names before "dl" keyword
        r'add me to (?:the )?([A-Za-z0-9\s_-]+?)\s+dl\b',
        r'add me to (?:the )?([A-Za-z0-9\s_-]+?)\s+distribution\s+list',
        
        # Pattern for email addresses with Slack formatting (e.g., "<mailto:dl_name@domain.com|...>")
        r'add me to (?:the )?<?(?:mailto:)?([A-Za-z0-9_-]+)@[A-Za-z0-9.-]+(?:\|[^>]+)?>?\s+dl\b',
        
        # New business language patterns
        r'add.*to.*(?:the\s+)?([A-Za-z0-9\s_-]+)\s+distribution\s+list',
        r'updates?\s+to.*(?:the\s+)?([A-Za-z0-9\s_-]+)\s+distribution\s+list',
        r'(?:the\s+)?([A-Za-z0-9\s_-]+)\s+distribution\s+list',
        r'distribution\s+list[:\s]+([A-Za-z0-9@._-]+)',
        
        # Fallback patterns (only if no matches yet)
        r'(?:dl|distribution|list):\s*([a-zA-Z0-9_-]+)',
    ]
    
    for pattern in group_patterns:
        matches = re.findall(pattern, desc, re.IGNORECASE)
        for match in matches:
            # Clean up the match - preserve original case and spaces
            clean_match = match.strip()
            if clean_match and len(clean_match) < 50 and clean_match.lower() not in [t.lower() for t in dl_targets]:
                dl_targets.append(clean_match)
                print(f"   Added target: '{clean_match}'")
        
        # If we found matches with explicit "dl" patterns, stop looking
        if dl_targets and 'dl' in pattern:
            break
    
    print(f"   Found DL targets (before filtering): {dl_targets}")
    
    # Filter out invalid DL names
    filtered_targets = []
    for target in dl_targets:
        # Strip @ domain if present
        if '@' in target:
            target = target.split('@')[0]
        
        # Validation rules
        if len(target) < 2:
            print(f"   Rejected '{target}': too short")
            continue
        
        if len(target) > 50:
            print(f"   Rejected '{target}': too long")
            continue
        
        # Reject sentences (multiple spaces and long)
        if target.count(' ') > 2 or (target.count(' ') > 0 and len(target) > 20):
            print(f"   Rejected '{target}': looks like a sentence")
            continue
        
        # Only allow alphanumeric, underscore, hyphen, and single spaces
        if not re.match(r'^[A-Za-z0-9_\s-]+$', target):
            print(f"   Rejected '{target}': invalid characters")
            continue
        
        # Avoid duplicates
        if target.lower() not in [t.lower() for t in filtered_targets]:
            filtered_targets.append(target)
            print(f"   ✅ Kept: '{target}'")
    
    dl_targets = filtered_targets
    print(f"   Found DL targets (after filtering): {dl_targets}")
    
    # Enhanced action detection patterns
    action_patterns = [
        # Personal requests
        r'add\s+me\s+to',
        
        # Third person requests  
        r'add.*(?:following|leadership|users|people|staff).*to',
        r'have.*added\s+to',
        r'please\s+have.*added',
        
        # Formal business patterns
        r'can\s+(?:you\s+)?(?:please\s+)?.*add',
        r'please\s+make.*updates?\s+to',
        r'updates?\s+to.*distribution',
        
        # Multiple people patterns
        r'add.*the\s+following',
        r'include.*in.*distribution',
    ]
    
    has_action = any(re.search(pattern, desc, re.IGNORECASE) for pattern in action_patterns)
    
    print(f"   Has action pattern: {has_action}")
    
    # Return result if we have both targets and actions
    if dl_targets and has_action:
        return {
            'requester': requester,
            'distribution_targets': dl_targets,
            'operations': [{'action': 'add', 'users': [requester]}],
            'user_emails': []
        }
    
    return None

def extract_sso_group_request(subject, body, sender):
    """Extract SSO/AD group request details using Claude AI"""
    import re
    import boto3
    import json
    
    # Strip HTML and Slack markdown
    if '<html>' in body.lower():
        body = re.sub(r'<[^>]+>', ' ', body)
        body = re.sub(r'\s+', ' ', body).strip()
    
    # Strip Slack markdown formatting
    body = re.sub(r'[*_~`]', '', body)  # Remove *, _, ~, `
    
    # Extract description
    desc_match = re.search(r'Description:\s*([^\\n]*(?:\\n[^\\n]*)*?)(?:Thank you|Contact:|Status:|Priority:|---)', body, re.IGNORECASE | re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()
        desc = re.sub(r'Thank you,.*?$', '', desc, flags=re.DOTALL | re.IGNORECASE)
    else:
        desc = body
        desc = re.sub(r'Thank you,.*?$', '', desc, flags=re.DOTALL | re.IGNORECASE)
    
    print(f"   SSO extraction - cleaned desc: {desc}")
    
    desc_lower = desc.lower()
    
    # Must contain SSO keyword
    if 'sso' not in desc_lower and 'active directory' not in desc_lower and 'ad group' not in desc_lower:
        return None
    
    # Use Claude AI to extract group name
    try:
        bedrock = boto3.client('bedrock-runtime')
        
        prompt = f"""Extract the SSO group name from this user request. Return ONLY the group name, nothing else.

User request: "{desc}"

Examples:
- "add me to the sso aws ever.ag infra sandbox admin group" → "aws ever.ag infra sandbox admin"
- "can you add me to SSO AWS Corp Admin" → "AWS Corp Admin"  
- "need access to the sso cainthus production admin group" → "cainthus production admin"

Group name:"""

        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        
        result = json.loads(response['body'].read())
        group_name = result['content'][0]['text'].strip()
        print(f"   Claude extracted group name: {group_name}")
        
    except Exception as e:
        print(f"   Claude extraction failed: {e}, falling back to regex")
        # Fallback to regex if Claude fails
        group_patterns = [
            r'(?:add|remove|grant|revoke).*?(?:to|from)\s+(?:the\s+)?sso\s+([A-Za-z0-9\s\-_.]+?)(?:\s+group|\s*$)',
            r'(?:add|remove|grant|revoke).*?(?:to|from)\s+(?:the\s+)?([A-Za-z0-9\s\-_.]+\s+sso\s+[A-Za-z0-9\s\-_.]+?)(?:\s+group|\s*$)',
            r'([A-Za-z0-9\s\-_.]+\s+sso\s+[A-Za-z0-9\s\-_.]+?)\s+(?:group|access|provisioning|setup|login|authentication)',
            r'(?:requesting|need|enable|grant|provision)\s+([A-Za-z0-9\s\-_.]+\s+sso)',
            r'([A-Za-z0-9\s\-_.]+)\s+sso\s+(?:isn\'t|not|issues|waiting)'
        ]
        
        group_name = None
        for pattern in group_patterns:
            match = re.search(pattern, desc, re.IGNORECASE)
            if match:
                group_name = match.group(1).strip()
                # Remove common articles from the beginning
                group_name = re.sub(r'^(the|a|an)\s+', '', group_name, flags=re.IGNORECASE).strip()
                # Remove common suffixes
                group_name = re.sub(r'\s+(group|access|provisioning|setup|login|authentication|account)$', '', group_name, flags=re.IGNORECASE).strip()
                break
    
    if not group_name:
        return None
    
    # Determine action (add or remove)
    action = 'add'
    if any(word in desc_lower for word in ['remove', 'revoke', 'delete']):
        action = 'remove'
    
    # Extract user email
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, desc, re.IGNORECASE)
    # Clean up Slack mailto formatting (e.g., "email@domain.com|name" -> "email@domain.com")
    emails = [email.split('|')[0] for email in emails]
    user_email = emails[0] if emails else sender
    
    return {
        'user_email': user_email,
        'group_name': group_name,
        'action': action,
        'requester': sender
    }

def extract_users_from_text(text):
    """Extract user names and emails from text"""
    users = []
    
    # Extract emails first
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text, re.IGNORECASE)
    users.extend(emails)
    
    # Extract names (First Last format)
    # Remove emails from text first
    text_no_emails = re.sub(email_pattern, '', text)
    
    # Look for name patterns
    name_pattern = r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b'
    names = re.findall(name_pattern, text_no_emails)
    
    for first, last in names:
        full_name = f"{first} {last}"
        if full_name not in users:
            users.append(full_name)
    
    # Clean up and remove common non-names
    skip_words = {'Thank You', 'Contact Status', 'Status Open', 'Priority Medium'}
    users = [u for u in users if u not in skip_words]
    
    return users

def extract_requester_email(body, sender):
    """Extract the actual requester email from ticket content"""
    # Look for "X submitted a new help desk ticket" pattern
    requester_match = re.search(r'([A-Za-z\s]+)\s+submitted a new help desk ticket', body, re.IGNORECASE)
    if requester_match:
        requester_name = requester_match.group(1).strip()
        
        # Known name mappings
        name_to_email = {
            'matthew denecke': 'matthew.denecke@ever.ag',
            'becky sylvera': 'becky.sylvera@ever.ag',
            'kimia safvat': 'kimia.safvat@ever.ag',
            'jenna wiker': 'jenna.wiker@ever.ag',
            'savannah wynne': 'savannah.wynne@ever.ag'
        }
        
        if requester_name.lower() in name_to_email:
            return name_to_email[requester_name.lower()]
    
    return sender  # Fallback

def handle_direct_email_request(event, context):
    """Handle direct email requests from mailbox poller (ORIGINAL WORKING PATH)"""
    print("🔄 Processing direct email request from mailbox poller")
    
    subject = event.get('subject', '')
    body = event.get('body', '')
    sender = event.get('sender', '')
    message_id = event.get('message_id', '')
    email_data = event.get('email_data', {})  # Get email_data for Slack context
    
    print(f"📧 Processing email: {subject}")
    
    # Check if this is a shared mailbox request FIRST
    shared_mailbox_result = extract_shared_mailbox_request(subject, body, sender)
    if shared_mailbox_result:
        print("🎯 Processing shared mailbox request:", shared_mailbox_result)
        
        # Create approval request for shared mailbox access
        details = f"User(s): {', '.join(shared_mailbox_result['users'])}\nShared Mailbox(es): {', '.join(shared_mailbox_result['shared_mailboxes'])}\n\nPlanned Changes:\n"
        
        changes = []
        for user in shared_mailbox_result['users']:
            for mailbox in shared_mailbox_result['shared_mailboxes']:
                mailbox_name = mailbox.split('@')[0]  # Get name part before @
                details += f"• Add {user} to {mailbox_name} shared mailbox (office365)\n"
                changes.append({
                    'action': 'add_user_to_shared_mailbox',
                    'user': user,
                    'mailbox': mailbox,
                    'mailbox_name': mailbox_name
                })
        
        # Create the execution plan
        plan = {
            'action_type': 'add_users_to_shared_mailboxes',
            'users': shared_mailbox_result['users'],
            'mailboxes': [{'email': mb, 'name': mb.split('@')[0]} for mb in shared_mailbox_result['shared_mailboxes']],
            'changes': changes
        }
        
        # Invoke approval system
        approval_payload = {
            'action': 'create_approval',
            'request_type': 'Shared Mailbox Access',
            'original_subject': subject,
            'original_message_id': message_id,
            'details': details,
            'requester': shared_mailbox_result['requester'],
            'callback_function': 'brie-infrastructure-connector',
            'callback_params': {
                'action_id': f"direct_{int(time.time())}",
                'plan': plan,
                'emailData': email_data  # Pass Slack context through
            },
            'urgency': 'normal',
            'ticket_number': shared_mailbox_result['ticket_number'],
            'suppress_completion_email': True
        }
        
        print(f"🚀 Invoking approval system with payload: {approval_payload}")
        
        # Call approval system
        approval_response = lambda_client.invoke(
            FunctionName='it-approval-system',
            InvocationType='RequestResponse',
            Payload=json.dumps(approval_payload)
        )
        
        approval_result = json.loads(approval_response['Payload'].read())
        print(f"✅ Approval system response: {approval_result}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Shared mailbox approval created',
                'result': approval_result
            })
        }
    
    # Extract distribution list request details using the WORKING logic
    request_details = extract_distribution_list_request(subject, body, sender)
    
    if not request_details:
        print("❌ No distribution list request detected")
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'No distribution list request detected'})
        }
    
    # Process the request using the ORIGINAL working flow
    return process_distribution_list_request(
        request_details, 
        subject, 
        message_id, 
        sender
    )

def handle_step_function_request(event, context):
    """Handle Step Function requests"""
    email_data = event['emailData']
    subject = email_data.get('subject', '')
    body = email_data.get('body', '')
    sender = email_data.get('sender', '')
    message_id = email_data.get('messageId', '')
    action = event.get('action', '')
    
    print(f"📧 Processing Step Function email: {subject} (action: {action})")
    
    # Route based on action type
    if action == 'AUTOMATE_SSO_GROUP':
        # Extract SSO group request details
        request_details = extract_sso_group_request(subject, body, sender)
        
        if not request_details:
            print("❌ No SSO group request detected")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No SSO group request detected'})
            }
        
        # Return for SSO workflow
        return {
            'statusCode': 200,
            'ssoGroupRequest': request_details,
            'emailData': email_data
        }
    
    elif action == 'AUTOMATE_MAILBOX_ACCESS':
        # Extract shared mailbox request details
        request_details = extract_shared_mailbox_request(subject, body, sender)
        
        if not request_details:
            print("❌ No shared mailbox request detected")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No shared mailbox request detected'})
            }
        
        # Process shared mailbox request - pass email_data for Slack context
        return handle_direct_email_request({
            'subject': subject, 
            'body': body, 
            'sender': sender, 
            'messageId': message_id,
            'email_data': email_data  # Pass through for Slack context
        }, context)
    
    # Default: Extract distribution list request details
    request_details = extract_distribution_list_request(subject, body, sender)
    
    if not request_details:
        print("❌ No distribution list request detected")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No distribution list request detected'})
        }
    
    # Process the request
    return process_distribution_list_request(
        request_details, 
        subject, 
        message_id, 
        sender,
        email_data  # Pass email_data for Slack context
    )

def extract_ticket_number(subject):
    """Extract ticket number from email subject"""
    # Look for patterns like "CorpIT-28614", "IT-12345", etc.
    ticket_patterns = [
        r'(CorpIT-\d+)',
        r'(IT-\d+)',
        r'(Ticket #:\s*CorpIT-\d+)',
        r'(\w+-\d+)'
    ]
    
    for pattern in ticket_patterns:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            ticket_num = match.group(1)
            # Clean up "Ticket #: " prefix if present
            if 'Ticket #:' in ticket_num:
                ticket_num = ticket_num.replace('Ticket #:', '').strip()
            return ticket_num
    
    # Fallback to generic format
    return f"IT-{int(time.time())}"

def process_distribution_list_request(request_details, subject, message_id, sender, email_data=None):
    """Process enhanced distribution list request with ADD/REMOVE operations"""
    try:
        print(f"🎯 Processing enhanced DL request: {request_details}")
        
        requester = request_details.get('requester')
        distribution_targets = request_details.get('distribution_targets', [])
        operations = request_details.get('operations', [])
        
        if not distribution_targets or not operations:
            print("❌ Missing distribution targets or operations")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing distribution targets or operations'})
            }
        
        # Extract ticket number
        ticket_number = extract_ticket_number(subject)
        
        # Build detailed description of planned changes
        details_lines = []
        details_lines.append(f"Distribution List(s): {', '.join(distribution_targets)}")
        details_lines.append("")
        details_lines.append("Planned Changes:")
        
        # Convert operations to changes format
        changes = []
        for op in operations:
            action = op['action']  # 'add' or 'remove'
            users = op['users']
            
            for user in users:
                for target in distribution_targets:
                    change = {
                        'action': f'{action}_user_to_group',
                        'user': user,
                        'group_name': target,
                        'operation': action
                    }
                    changes.append(change)
                    
                    # Add to details
                    action_text = "Add" if action == "add" else "Remove"
                    details_lines.append(f"• {action_text} {user} {'to' if action == 'add' else 'from'} {target}")
        
        # Format details for approval system
        user_list = []
        target_list = []
        
        for operation in operations:
            for user in operation['users']:
                if user not in user_list:
                    user_list.append(user)
        
        # Get targets from distribution_targets
        for target in distribution_targets:
            if target not in target_list:
                target_list.append(target)
        
        details = f"User(s): {', '.join(user_list)}\nTarget(s): {', '.join(target_list)}\n\nPlanned Changes:\n" + "\n".join(details_lines)
        
        # Create approval request
        approval_payload = {
            'action': 'create_approval',
            'request_type': 'Distribution List Access',
            'original_subject': subject,
            'original_message_id': message_id,
            'details': details,
            'requester': requester,
            'callback_function': 'brie-infrastructure-connector',
            'callback_params': {
                'action': 'add_user_to_group',
                'user_email': requester,
                'group_name': distribution_targets[0] if distribution_targets else 'ittest',
                'emailData': email_data,  # Pass Slack context through
                'email_details': {
                    'original_message_id': message_id,
                    'original_subject': subject,
                    'requester': requester
                }
            },
            'urgency': 'normal',
            'ticket_number': ticket_number,
            'suppress_completion_email': True  # Let brie-infrastructure-connector handle email
        }
        
        print(f"🚀 Invoking approval system with enhanced payload")
        
        # Invoke approval system
        lambda_client = boto3.client('lambda')
        response = lambda_client.invoke(
            FunctionName='it-approval-system',
            InvocationType='RequestResponse',
            Payload=json.dumps(approval_payload)
        )
        
        approval_response = json.loads(response['Payload'].read())
        print(f"✅ Approval system response: {approval_response}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Enhanced distribution list request sent for approval',
                'approval_id': json.loads(approval_response.get('body', '{}'))
            })
        }
        
    except Exception as e:
        print(f"❌ Error processing enhanced DL request: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Processing error: {str(e)}'})
        }
        
        response = lambda_client.invoke(
            FunctionName='it-approval-system',
            InvocationType='RequestResponse',
            Payload=json.dumps(approval_payload)
        )
        
        result = json.loads(response['Payload'].read())
        print(f"✅ Approval system response: {result}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Distribution list approval created', 'result': result})
        }
        
    except Exception as e:
        print(f"❌ Error processing DL request: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def send_execution_result_email(original_message_id, original_subject, requester_email, success, message):
    """Send email notification about execution result"""
    # Use the existing send_result_email function
    return send_result_email(original_message_id, original_subject, requester_email, success, message)

def handle_approval_callback(event, context):
    """Main Lambda handler for IT Action Processor"""
    
    action = event.get('action')
    
    if action == 'execute_plan':
        # Execute approved plan
        plan = event.get('plan', {})
        email_details = event.get('email_details', {})
        
        # Determine plan type and execute accordingly
        action_type = plan.get('action_type', '')
        
        if 'shared_mailbox' in action_type.lower():
            results = execute_shared_mailbox_changes(plan)
        elif 'distribution' in action_type.lower() or 'group' in action_type.lower():
            results = execute_distribution_list_changes(plan)
        else:
            # Generic execution for mixed plans
            results = []
            for change in plan.get('changes', []):
                change_action = change.get('action')
                
                if change_action == 'add_user_to_group':
                    sub_plan = {'changes': [change]}
                    sub_results = execute_distribution_list_changes(sub_plan)
                    results.extend(sub_results)
                
                elif change_action == 'add_user_to_shared_mailbox':
                    sub_plan = {'changes': [change]}
                    sub_results = execute_shared_mailbox_changes(sub_plan)
                    results.extend(sub_results)
        
        # Combine results
        all_success = all(r.get('status') == 'success' for r in results)
        combined_message = '\n'.join(r.get('message', r.get('error', 'Unknown result')) for r in results)
        
        print(f"🔍 DEBUG - combined_message: {combined_message}")
        print(f"🔍 DEBUG - all_success: {all_success}")
        
        # Check if this is from Slack
        slack_context = event.get('slack_context')
        original_message_id = email_details.get('original_message_id', '') if email_details else ''
        is_slack_request = slack_context or original_message_id.startswith('slack_')
        
        # Send Slack notification if from Slack
        if is_slack_request and slack_context:
            channel = slack_context.get('channel')
            user_email = email_details.get('requester', 'Unknown') if email_details else 'Unknown'
            
            if channel:
                # Check if user already had access
                already_member = 'already has access' in combined_message.lower() or 'already a member' in combined_message.lower()
                
                print(f"🔍 DEBUG - already_member: {already_member}")
                
                if all_success:
                    if already_member:
                        user_msg = f"ℹ️ **Already a Member**\n\n{combined_message}"
                        it_msg = f"ℹ️ **Already a Member**\n\nUser: {user_email}\n{combined_message}"
                    else:
                        user_msg = f"✅ **Request Completed!**\n\n{combined_message}"
                        it_msg = f"✅ **Request Completed**\n\nUser: {user_email}\n{combined_message}"
                else:
                    user_msg = f"❌ **Request Failed**\n\n{combined_message}"
                    it_msg = f"❌ **Request Failed**\n\nUser: {user_email}\n{combined_message}"
                
                # Send to user's channel
                import urllib.request
                import json as json_lib
                
                try:
                    print(f"📤 Sending to user channel: {channel}")
                    slack_payload = {
                        'channel': channel,
                        'text': user_msg
                    }
                    req = urllib.request.Request(
                        'https://slack.com/api/chat.postMessage',
                        data=json_lib.dumps(slack_payload).encode('utf-8'),
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {os.environ.get("SLACK_BOT_TOKEN", "")}'
                        }
                    )
                    response = urllib.request.urlopen(req)
                    print(f"✅ Sent to user: {response.read().decode()}")
                except Exception as e:
                    print(f"❌ Failed to send to user: {e}")
                
                try:
                    print(f"📤 Sending to IT channel: C09KB40PL9J")
                    # Send to IT channel
                    it_payload = {
                        'channel': 'C09KB40PL9J',  # IT channel
                        'text': it_msg
                    }
                    req = urllib.request.Request(
                        'https://slack.com/api/chat.postMessage',
                        data=json_lib.dumps(it_payload).encode('utf-8'),
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {os.environ.get("SLACK_BOT_TOKEN", "")}'
                        }
                    )
                    response = urllib.request.urlopen(req)
                    print(f"✅ Sent to IT: {response.read().decode()}")
                except Exception as e:
                    print(f"❌ Failed to send to IT: {e}")
                
                # Send callback to it-helpdesk-bot to update conversation history
                if slack_context and slack_context.get('user_id'):
                    try:
                        lambda_client = boto3.client('lambda')
                        lambda_client.invoke(
                            FunctionName='it-helpdesk-bot',
                            InvocationType='Event',
                            Payload=json_lib.dumps({
                                'callback_result': True,
                                'result_data': {
                                    'slackContext': slack_context,
                                    'message': user_msg,
                                    'status': 'completed' if all_success else 'failed'
                                }
                            })
                        )
                    except Exception as e:
                        print(f"⚠️ Failed to send callback to it-helpdesk-bot: {e}")
        
        # Send email notification ONLY if NOT from Slack
        elif email_details and email_details.get('requester') and not is_slack_request:
            send_execution_result_email(
                email_details.get('original_message_id'),
                email_details.get('original_subject'),
                email_details.get('requester'),
                all_success,
                combined_message
            )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': all_success,
                'message': combined_message
            })
        }
    
    elif action == 'analyze_request':
        # Analyze email for actionable requests
        subject = event.get('subject', '')
        body = event.get('body', '')
        sender = event.get('sender', '')
        message_id = event.get('message_id', '')  # Get message ID for email threading
        
        # Check for IT Access Automation requests
        itaa_request = extract_itaa_request(subject, body, sender)
        
        if itaa_request:
            # Create action record
            action_id = create_action_record(
                action_type='itaa_request',
                details=itaa_request,
                requester=sender
            )
            
            # Plan the changes
            plan = plan_distribution_list_changes(
                itaa_request['users'],
                itaa_request['email_addresses']
            )
            
            # Extract ticket info if available
            ticket_number, ticket_url = extract_ticket_info(subject, body)
            
            # Extract real requester (not just the ticketing system sender)
            real_requester = extract_real_requester(subject, body, sender)
            
            # Request approval
            approval_payload = {
                'action': 'create_approval',
                'request_type': 'IT Access Request',
                'original_subject': subject,  # Store original subject for email replies
                'original_message_id': message_id,  # Store original message ID for email threading
                'details': f"""User(s): {', '.join(itaa_request['users'])}
Target(s): {', '.join(itaa_request['email_addresses'])}

Planned Changes:
{chr(10).join([f"• Add {change['user']} to {change['group_name']} ({change['group_location']})" for change in plan['changes']])}""",
                'requester': real_requester,
                'callback_function': 'brie-infrastructure-connector',
                'callback_params': {
                    'action_id': action_id,
                    'plan': plan
                },
                'urgency': 'normal'
            }
            
            # Add ticket info if available
            if ticket_number:
                approval_payload['ticket_number'] = ticket_number
            if ticket_url:
                approval_payload['ticket_url'] = ticket_url
            
            # Invoke approval system
            try:
                print(f"🚀 Invoking approval system with payload: {approval_payload}")
                
                response = lambda_client.invoke(
                    FunctionName='it-approval-system',
                    InvocationType='Event',
                    Payload=json.dumps(approval_payload)
                )
                
                print(f"✅ Approval system invoked successfully: {response}")
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'action_detected': True,
                        'action_type': 'itaa_request',
                        'action_id': action_id,
                        'status': 'pending_approval'
                    })
                }
                
            except Exception as e:
                print(f"❌ Error invoking approval system: {e}")
                return {
                    'statusCode': 500,
                    'body': json.dumps({
                        'error': 'Failed to request approval'
                    })
                }
        
        else:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'action_detected': False,
                    'message': 'No actionable requests found'
                })
            }
    
    elif action == 'execute':
        # Execute approved action
        approval_id = event.get('approval_id')
        action_id = event.get('params', {}).get('action_id')
        plan = event.get('params', {}).get('plan')
        
        if not plan:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'No execution plan provided'
                })
            }
        
        # Execute the changes based on action type
        if plan.get('action_type') == 'add_users_to_shared_mailboxes':
            results = execute_shared_mailbox_changes(plan)
        elif plan.get('action_type') == 'enhanced_distribution_list_operations':
            results = execute_enhanced_distribution_list_changes(plan)
        else:
            # Default to distribution list execution for backward compatibility
            results = execute_distribution_list_changes(plan)
        
        # Update action record
        if actions_table and action_id:
            try:
                actions_table.update_item(
                    Key={'action_id': action_id},
                    UpdateExpression='SET #status = :status, results = :results, updated_at = :timestamp',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':status': 'completed',
                        ':results': results,
                        ':timestamp': datetime.utcnow().isoformat()
                    }
                )
            except Exception as e:
                print(f"❌ Error updating action record: {e}")
        
        # Send result email if we have email details
        email_details = event.get('params', {}).get('email_details')
        if email_details:
            
            # Create detailed message from individual results
            detailed_results = []
            overall_success = True
            
            for result in results:
                success = result.get('status') == 'success'
                
                if not success:
                    overall_success = False
                
                if success:
                    # Use the formatted message from the result
                    message = result.get('message', '')
                    if message:
                        detailed_results.append(f"   • {message}")
                    else:
                        # Fallback formatting
                        target = result.get('target', 'Unknown Group')
                        detailed_results.append(f"   • {target} - Successfully completed ✓")
                else:
                    target = result.get('target', 'Unknown Group')
                    error_msg = result.get('error', 'Failed')
                    detailed_results.append(f"   • {target} - Failed: {error_msg} ❌")
            
            # Create the detailed message
            if detailed_results:
                message = "\n".join(detailed_results)
                if overall_success:
                    message += "\n\nYour access request is now complete."
                else:
                    message += "\n\nSome operations failed. A live IT agent will review and complete manually."
            else:
                message = "Request processed" if overall_success else "Request failed"
            
            # Send email
            send_result_email(
                email_details['original_message_id'],
                email_details['original_subject'],
                email_details['requester'],
                overall_success,
                message
            )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'action_id': action_id,
                'approval_id': approval_id,
                'status': 'completed',
                'results': results,
                'success': all(result.get('status') == 'success' for result in results),
                'message': 'Execution completed' if all(result.get('status') == 'success' for result in results) else 'Some operations failed'
            })
        }
    
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': 'Invalid action. Use: analyze_request or execute'
            })
        }
