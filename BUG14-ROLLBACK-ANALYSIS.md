# Bug #14 Rollback Analysis

## Status
✅ **ROLLED BACK** - Pre-bug14 version restored at 15:10 CST

## Critical Errors Found

### Error 1: Type Mismatch - Decimal vs Float
**Location:** `get_or_create_conversation()` function
**Error:** `unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`

```python
# Line causing error:
last_msg_time = recent.get('last_message_timestamp', recent.get('timestamp', 0))
time_since_last = datetime.utcnow().timestamp() - last_msg_time
```

**Problem:**
- DynamoDB returns numbers as `Decimal` type (from boto3)
- `datetime.utcnow().timestamp()` returns `float`
- Python cannot subtract Decimal from float directly

**Fix Required:**
```python
from decimal import Decimal

last_msg_time = recent.get('last_message_timestamp', recent.get('timestamp', 0))
# Convert Decimal to float
if isinstance(last_msg_time, Decimal):
    last_msg_time = float(last_msg_time)
time_since_last = datetime.utcnow().timestamp() - last_msg_time
```

### Error 2: Wrong Table Name
**Error:** `ResourceNotFoundException: Requested resource not found`
**Context:** "Error logging interaction"

**Problem:**
- Code references wrong DynamoDB table name
- Actual table: `brie-it-helpdesk-bot-interactions`
- Code may be using: `brie-it-interactions` or similar

**Need to verify:** Check all table references in the code

## Impact

### What Broke
1. ❌ Conversations not created in DynamoDB
2. ❌ No conversation tracking
3. ❌ Bot responds but doesn't save interaction
4. ❌ Dashboard shows no new conversations

### What Still Worked
1. ✅ Bot receives messages
2. ✅ Bot sends responses
3. ✅ Slack integration functional

## Root Cause Analysis

### Why This Wasn't Caught
1. **No type conversion** - Assumed DynamoDB returns int/float, but it returns Decimal
2. **Table name mismatch** - May have been using wrong constant or variable
3. **No local testing** - Deployed directly to production
4. **No integration test** - Would have caught DynamoDB type issues

## Fixes Required

### Fix 1: Handle Decimal Types (CRITICAL)
All timestamp comparisons need Decimal handling:

```python
from decimal import Decimal

def safe_timestamp_diff(timestamp_value):
    """Convert DynamoDB Decimal to float for timestamp math"""
    if isinstance(timestamp_value, Decimal):
        return float(timestamp_value)
    return timestamp_value
```

Apply to:
- Line ~40: `get_or_create_conversation()` - time_since_last calculation
- Line ~2490: `auto_resolve` handler - time_since_last calculation  
- Line ~2470: `engagement_prompt` handler - time_since_last calculation
- Line ~2515: approval timeout - conversation_age_days calculation

### Fix 2: Verify Table Name (CRITICAL)
Check all references to interactions table:

```bash
grep -n "interactions_table\|Table(" lambda_it_bot_confluence.py
```

Ensure all use: `brie-it-helpdesk-bot-interactions`

### Fix 3: Add Type Safety
Import Decimal at top of file:
```python
from decimal import Decimal
```

## Testing Plan Before Re-Deploy

### 1. Local Type Testing
```python
# Test Decimal conversion
from decimal import Decimal
timestamp = Decimal('1760472496')
current = datetime.utcnow().timestamp()
diff = current - float(timestamp)  # Should work
```

### 2. DynamoDB Table Verification
```bash
aws dynamodb describe-table \
  --table-name brie-it-helpdesk-bot-interactions \
  --region us-east-1 \
  --profile AWSCorp
```

### 3. Integration Test
1. Deploy to test Lambda (if available)
2. Send test message
3. Verify DynamoDB entry created
4. Check CloudWatch for errors

### 4. Production Smoke Test
1. Deploy to production
2. Send test message immediately
3. Check DynamoDB within 30 seconds
4. Rollback if any errors

## Deployment Checklist

Before re-deploying bug #14 fix:

- [ ] Add `from decimal import Decimal` import
- [ ] Add `safe_timestamp_diff()` helper function
- [ ] Update all timestamp comparisons to use helper
- [ ] Verify table name is `brie-it-helpdesk-bot-interactions`
- [ ] Test locally with Decimal types
- [ ] Review all DynamoDB get/scan operations
- [ ] Add error handling for type conversions
- [ ] Test on one conversation before full deploy
- [ ] Monitor CloudWatch logs during deployment
- [ ] Have rollback command ready

## Rollback Info

**Restore Point:** Tag `pre-bug14-timeout-fix`
**Rollback Command:**
```bash
cd /Users/matt/Brie-IT-Agent
git checkout pre-bug14-timeout-fix
zip -q lambda_package.zip lambda_it_bot_confluence.py
aws lambda update-function-code \
  --function-name it-helpdesk-bot \
  --zip-file fileb://lambda_package.zip \
  --region us-east-1 \
  --profile AWSCorp
```

## Next Steps

1. Fix Decimal type handling
2. Verify table names
3. Add comprehensive error handling
4. Test locally with DynamoDB types
5. Create new deployment with fixes
6. Monitor closely during deployment
