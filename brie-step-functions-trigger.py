import json
import boto3
import os
import urllib.request
import urllib.parse

# AWS clients
stepfunctions = boto3.client('stepfunctions')

# Office 365 credentials
TENANT_ID = "3d90a358-2976-40f4-8588-45ed47a26302"
CLIENT_ID = "97d0a776-cc4a-4c2d-a774-fba7c66938f7"
CLIENT_SECRET = os.environ.get('CLIENT_SECRET', 'AZURE_CLIENT_SECRET')
MAILBOX_EMAIL = "brieitagent@ever.ag"

# Step Functions ARN
STEP_FUNCTIONS_ARN = "arn:aws:states:us-east-1:843046951786:stateMachine:brie-ticket-processor"

def get_access_token():
    """Get access token for Microsoft Graph API"""
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
        token_data = json.loads(response.read().decode('utf-8'))
        return token_data['access_token']

def check_for_emails(access_token):
    """Check if there are unread emails"""
    # Properly encode the filter parameter
    filter_param = urllib.parse.quote("isRead eq false")
    url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX_EMAIL}/messages?$filter={filter_param}&$top=1"
    
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {access_token}')
    req.add_header('Content-Type', 'application/json')
    
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        return len(data.get('value', [])) > 0

def lambda_handler(event, context):
    """Check for emails and trigger Step Functions if found"""
    try:
        print("Starting Brie IT Agent mailbox check")
        
        # Get access token
        access_token = get_access_token()
        
        # Check for unread emails
        has_emails = check_for_emails(access_token)
        
        if has_emails:
            print("Found unread emails - triggering Step Functions workflow")
            
            # Trigger Step Functions workflow
            response = stepfunctions.start_execution(
                stateMachineArn=STEP_FUNCTIONS_ARN,
                name=f"email-processing-{int(context.aws_request_id.replace('-', '')[:10], 16)}",
                input=json.dumps({})
            )
            
            print(f"Step Functions execution started: {response['executionArn']}")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Step Functions workflow triggered',
                    'executionArn': response['executionArn']
                })
            }
        else:
            print("No unread emails found")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No unread emails found'})
            }
        
    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
