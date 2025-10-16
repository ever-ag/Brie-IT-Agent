import boto3
import json
from datetime import datetime, timedelta
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('brie-it-helpdesk-bot-interactions')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    """API handler for dashboard"""
    
    # Enable CORS
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
    }
    
    # Handle OPTIONS for CORS
    if event.get('httpMethod') == 'OPTIONS' or event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': ''}
    
    # Support both API Gateway v1 and v2 formats
    path = event.get('rawPath') or event.get('path', '')
    
    try:
        if path == '/interactions':
            return get_interactions(event, headers)
        elif path == '/stats':
            return get_stats(headers)
        elif path == '/close-conversation':
            return close_conversation(event, headers)
        else:
            return {
                'statusCode': 404,
                'headers': headers,
                'body': json.dumps({'error': 'Not found'})
            }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': str(e)})
        }

def get_interactions(event, headers):
    """Get interactions with optional filters"""
    params = event.get('queryStringParameters') or {}
    
    # Get date range
    days = int(params.get('days', 30))
    start_timestamp = int((datetime.utcnow() - timedelta(days=days)).timestamp())
    
    # Scan table (for small datasets, use scan; for large, use query with GSI)
    response = table.scan()
    items = response.get('Items', [])
    
    # Filter by timestamp
    items = [item for item in items if item.get('timestamp', 0) >= start_timestamp]
    
    # Sort by timestamp descending
    items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    # Limit results
    limit = int(params.get('limit', 100))
    items = items[:limit]
    
    return {
        'statusCode': 200,
        'headers': headers,
        'body': json.dumps({'interactions': items}, cls=DecimalEncoder)
    }

def get_stats(headers):
    """Get statistics for dashboard"""
    # Get all interactions
    response = table.scan()
    items = response.get('Items', [])
    
    # Calculate stats
    total = len(items)
    
    # Count by type
    by_type = {}
    for item in items:
        itype = item.get('interaction_type', 'Unknown')
        by_type[itype] = by_type.get(itype, 0) + 1
    
    # Count by outcome
    by_outcome = {}
    for item in items:
        outcome = item.get('outcome', 'Unknown')
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
    
    # Calculate deflection rate (resolved by Brie + self-service)
    deflected = by_outcome.get('Resolved by Brie', 0) + by_outcome.get('Self-Service Solution', 0)
    deflection_rate = round((deflected / total * 100) if total > 0 else 0, 1)
    
    # Recent activity (last 7 days)
    seven_days_ago = int((datetime.utcnow() - timedelta(days=7)).timestamp())
    recent = [item for item in items if item.get('timestamp', 0) >= seven_days_ago]
    
    # Daily trend for last 7 days
    daily_counts = {}
    for item in recent:
        date = item.get('date', '')[:10]  # Get YYYY-MM-DD
        daily_counts[date] = daily_counts.get(date, 0) + 1
    
    stats = {
        'total_interactions': total,
        'deflection_rate': deflection_rate,
        'by_type': by_type,
        'by_outcome': by_outcome,
        'recent_count': len(recent),
        'daily_trend': daily_counts
    }
    
    return {
        'statusCode': 200,
        'headers': headers,
        'body': json.dumps(stats, cls=DecimalEncoder)
    }

def close_conversation(event, headers):
    """Close a conversation by updating its outcome"""
    try:
        body = json.loads(event.get('body', '{}'))
        interaction_id = body.get('interaction_id')
        timestamp = body.get('timestamp')
        
        if not interaction_id or not timestamp:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Missing interaction_id or timestamp'})
            }
        
        table.update_item(
            Key={'interaction_id': interaction_id, 'timestamp': timestamp},
            UpdateExpression='SET outcome = :outcome',
            ExpressionAttributeValues={':outcome': 'Cancelled - Manual Close'}
        )
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': str(e)})
        }
