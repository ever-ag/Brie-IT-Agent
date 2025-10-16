import json
import boto3

ssm = boto3.client('ssm')
BESPIN_INSTANCE_ID = "i-0dca7766c8de43f08"

def check_membership(user_email, group_name):
    """Check if user is already a member of the group"""
    try:
        ps_script = f"""
$ErrorActionPreference = "Stop"
try {{
    # Get user
    $userEmail = "{user_email}"
    $user = Get-ADUser -Filter "EmailAddress -eq '$userEmail'"
    
    if (-not $user) {{
        # Try alias search
        $user = Get-ADUser -Filter "proxyAddresses -like '*$userEmail*'" -Properties proxyAddresses
        if (-not $user) {{
            Write-Output "USER_NOT_FOUND"
            exit 0
        }}
    }}
    
    # Get group
    $group = Get-ADGroup -Filter "Name -eq '{group_name}'"
    if (-not $group) {{
        Write-Output "GROUP_NOT_FOUND"
        exit 0
    }}
    
    # Check membership
    $isMember = Get-ADGroupMember -Identity $group.DistinguishedName | Where-Object {{ $_.DistinguishedName -eq $user.DistinguishedName }}
    if ($isMember) {{
        Write-Output "ALREADY_MEMBER"
    }} else {{
        Write-Output "NOT_MEMBER"
    }}
}} catch {{
    Write-Output "ERROR: $_"
}}
"""
        
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [ps_script]},
            TimeoutSeconds=30
        )
        
        command_id = response['Command']['CommandId']
        
        import time
        time.sleep(2)
        
        output_response = ssm.get_command_invocation(
            CommandId=command_id,
            InstanceId=BESPIN_INSTANCE_ID
        )
        
        output = output_response['StandardOutputContent'].strip()
        print(f"Membership check output: {output}")
        
        if "ALREADY_MEMBER" in output:
            return "ALREADY_MEMBER"
        elif "NOT_MEMBER" in output:
            return "NOT_MEMBER"
        elif "USER_NOT_FOUND" in output:
            return "USER_NOT_FOUND"
        elif "GROUP_NOT_FOUND" in output:
            return "GROUP_NOT_FOUND"
        else:
            return "ERROR"
        
    except Exception as e:
        print(f"Error checking membership: {e}")
        return "ERROR"

def check_group_type(group_name):
    """Check if group is SSO/AD group or Distribution List - returns list of matches"""
    try:
        # Escape single quotes in group name
        safe_name = group_name.replace("'", "''")
        
        ps_script = f"""
Write-Output "START"
try {{
    $adGroups = Get-ADGroup -Filter "Name -like '*{safe_name}*'" -ErrorAction SilentlyContinue
    if ($adGroups) {{
        if ($adGroups -is [array]) {{
            Write-Output "Found $($adGroups.Count) AD groups"
            foreach ($group in $adGroups) {{
                Write-Output "SSO_GROUP|$($group.Name)"
            }}
        }} else {{
            Write-Output "Found 1 AD groups"
            Write-Output "SSO_GROUP|$($adGroups.Name)"
        }}
    }}
}} catch {{
    Write-Output "AD_ERROR: $_"
}}

try {{
    # Use certificate-based authentication with correct app
    $AppId = "c33fc45c-9313-4f45-ac31-baf568616137"
    $Organization = "ever.ag"
    $CertThumbprint = "FB19D5A06678A28BFAF72C31A9A0155F1058295F"
    
    Connect-ExchangeOnline -CertificateThumbprint $CertThumbprint -AppId $AppId -Organization $Organization
    $dls = Get-DistributionGroup -Filter "Name -like '*{safe_name}*' -or PrimarySmtpAddress -like '*{safe_name}*'"
    if ($dls) {{
        if ($dls -is [array]) {{
            Write-Output "Found $($dls.Count) DLs"
            foreach ($dl in $dls) {{
                Write-Output "DISTRIBUTION_LIST|$($dl.Name)"
            }}
        }} else {{
            Write-Output "Found 1 DLs"
            Write-Output "DISTRIBUTION_LIST|$($dls.Name)"
        }}
    }}
    Disconnect-ExchangeOnline -Confirm:$false
}} catch {{
    Write-Output "DL_ERROR: $_"
}}

Write-Output "END"
"""
        
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [ps_script]},
            TimeoutSeconds=30
        )
        
        command_id = response['Command']['CommandId']
        
        import time
        # Wait for command to complete (up to 30 seconds for Exchange connection)
        status = 'InProgress'
        for i in range(15):
            time.sleep(2)
            output_response = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=BESPIN_INSTANCE_ID
            )
            status = output_response.get('Status')
            if status in ['Success', 'Failed']:
                break
        
        output = output_response['StandardOutputContent'].strip()
        error_output = output_response.get('StandardErrorContent', '').strip()
        print(f"SSM Command Status: {status}")
        print(f"Group type check output length: {len(output)} chars")
        if error_output:
            print(f"Group type check errors: {error_output}")
        
        if status not in ['Success', 'Failed']:
            print(f"PowerShell script timed out after 30 seconds, status: {status}")
            return None
        
        if not output or "END" not in output:
            print(f"PowerShell script did not complete successfully. Output: {output[:500]}")
            return None
        
        # Parse results
        matches = []
        for line in output.split('\n'):
            line = line.strip()
            if '|' in line and ('SSO_GROUP|' in line or 'DISTRIBUTION_LIST|' in line):
                group_type, group_name_found = line.split('|', 1)
                matches.append({
                    'type': group_type,
                    'name': group_name_found
                })
        
        return matches if matches else None
        
    except Exception as e:
        print(f"Error checking group type: {e}")
        return None

def lambda_handler(event, context):
    """Validate SSO group request - check user and group exist in AD"""
    try:
        print(f"Validating SSO group request: {json.dumps(event)}")
        
        # Handle check_group_type action
        if event.get('action') == 'check_group_type':
            group_name = event.get('group_name', '')
            matches = check_group_type(group_name)
            return {
                'statusCode': 200,
                'body': json.dumps({'matches': matches, 'search_term': group_name})
            }
        
        # Handle check_membership action
        if event.get('action') == 'check_membership':
            user_email = event.get('user_email', '')
            group_name = event.get('group_name', '')
            membership_status = check_membership(user_email, group_name)
            return {
                'statusCode': 200,
                'body': json.dumps({'membership_status': membership_status, 'user_email': user_email, 'group_name': group_name})
            }
        
        sso_request = event.get('ssoGroupRequest', {})
        user_email = sso_request.get('user_email')
        group_name = sso_request.get('group_name')
        action = sso_request.get('action', 'add')
        
        if not user_email or not group_name:
            return {
                'statusCode': 400,
                'valid': False,
                'error': 'Missing user email or group name'
            }
        
        # PowerShell script to validate user, group, and membership
        ps_script = f"""
$ErrorActionPreference = "Stop"

try {{
    # Extract username from email
    $userEmail = "{user_email}"
    $userName = $userEmail.Split('@')[0]
    
    # Check if user exists
    $user = Get-ADUser -Filter "EmailAddress -eq '$userEmail'" -ErrorAction SilentlyContinue
    if (-not $user) {{
        Write-Output "ERROR: User $userEmail not found in Active Directory"
        exit 1
    }}
    
    # Check if group exists
    $group = Get-ADGroup -Filter "Name -eq '{group_name}'" -ErrorAction SilentlyContinue
    if (-not $group) {{
        Write-Output "ERROR: Group '{group_name}' not found in Active Directory"
        exit 1
    }}
    
    # Check current membership
    $isMember = Get-ADGroupMember -Identity $group.DistinguishedName | Where-Object {{ $_.SamAccountName -eq $user.SamAccountName }}
    
    if ("{action}" -eq "add" -and $isMember) {{
        Write-Output "ALREADY_MEMBER: User $userEmail is already a member of '{group_name}'"
        exit 2
    }}
    
    if ("{action}" -eq "remove" -and -not $isMember) {{
        Write-Output "NOT_MEMBER: User $userEmail is not a member of '{group_name}'"
        exit 3
    }}
    
    # Validation passed
    Write-Output "VALID: User=$($user.SamAccountName), Group=$($group.DistinguishedName)"
    
}} catch {{
    Write-Output "ERROR: $_"
    exit 1
}}
"""
        
        # Execute validation on domain controller
        response = ssm.send_command(
            InstanceIds=[BESPIN_INSTANCE_ID],
            DocumentName='AWS-RunPowerShellScript',
            Parameters={'commands': [ps_script]},
            TimeoutSeconds=30
        )
        
        command_id = response['Command']['CommandId']
        print(f"Validation command ID: {command_id}")
        
        # Wait for command to complete
        import time
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
        exit_code = result.get('ResponseCode', -1)
        
        print(f"Validation output: {output}")
        print(f"Exit code: {exit_code}")
        
        # Parse result
        if exit_code == 0 and 'VALID:' in output:
            return {
                'statusCode': 200,
                'valid': True,
                'ssoGroupRequest': sso_request,
                'validationOutput': output
            }
        elif exit_code == 2:
            # Already a member
            return {
                'statusCode': 200,
                'valid': False,
                'alreadyMember': True,
                'message': output
            }
        elif exit_code == 3:
            # Not a member (for remove action)
            return {
                'statusCode': 200,
                'valid': False,
                'notMember': True,
                'message': output
            }
        else:
            # Validation failed
            return {
                'statusCode': 200,
                'valid': False,
                'error': output or error_output
            }
        
    except Exception as e:
        print(f"Error validating SSO group request: {e}")
        return {
            'statusCode': 500,
            'valid': False,
            'error': str(e)
        }
