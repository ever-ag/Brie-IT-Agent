import json
import boto3

def lambda_handler(event, context):
    """Look up user by display name in Active Directory"""
    
    display_name = event.get('displayName', '').strip()
    
    if not display_name:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Display name is required'})
        }
    
    print(f"Looking up user: {display_name}")
    
    # Mock implementation for testing - in production this would connect to AD
    # For now, simulate some common name variations
    mock_users = {
        'alex goins': [
            {
                'displayName': 'Alexander Goins',
                'mail': 'alexander.goins@ever.ag',
                'samAccountName': 'agoins'
            }
        ],
        'alex': [
            {
                'displayName': 'Alexander Goins',
                'mail': 'alexander.goins@ever.ag',
                'samAccountName': 'agoins'
            },
            {
                'displayName': 'Alex Smith',
                'mail': 'alex.smith@ever.ag',
                'samAccountName': 'asmith'
            }
        ],
        'john smith': [
            {
                'displayName': 'John Smith',
                'mail': 'john.smith@ever.ag',
                'samAccountName': 'jsmith'
            }
        ]
    }
    
    # Normalize search term
    search_key = display_name.lower().strip()
    
    # Find matching users
    users = mock_users.get(search_key, [])
    
    print(f"Found {len(users)} users matching '{display_name}'")
    
    return {
        'statusCode': 200,
        'body': json.dumps({'users': users})
    }
