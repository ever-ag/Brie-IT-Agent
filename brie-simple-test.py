import json
import boto3

def lambda_handler(event, context):
    """Simple test to manually trigger Brie IT Agent logic"""
    
    try:
        print("Manual Brie IT Agent test")
        
        # Simulate processing an email that's in the mailbox
        # For now, let's just test the SES sending capability
        
        ses_client = boto3.client('ses', region_name='us-east-1')
        
        # Send a test response
        test_body = """Hello,

This is a test response from Brie IT Agent. The system is working and can send automated responses.

If you received this, the Brie IT Agent is successfully configured and ready to help with IT support tickets.

Best regards,
Brie IT Agent
Ever.Ag IT Support"""

        response = ses_client.send_email(
            Source="brieitagent@ever.ag",
            Destination={'ToAddresses': ["matthew.denecke@ever.ag"]},
            Message={
                'Subject': {'Data': "Brie IT Agent Test - System Working"},
                'Body': {'Text': {'Data': test_body}}
            }
        )
        
        print(f"Test email sent successfully: {response['MessageId']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Brie IT Agent test completed successfully',
                'email_sent': True,
                'message_id': response['MessageId']
            })
        }
        
    except Exception as e:
        print(f"Error in test: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': f'Error: {str(e)}'})
        }
