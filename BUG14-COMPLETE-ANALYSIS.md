# Bug #14 Complete Analysis & Fix Plan

## Rollback Status
✅ **ROLLED BACK** at 15:10 CST - System operational

## Critical Errors Found

### Error 1: Type Mismatch - Decimal vs Float ⚠️ CRITICAL
**Location:** `get_or_create_conversation()` line ~40
**Error:** `unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`

**Code:**
```python
last_msg_time = recent.get('last_message_timestamp', recent.get('timestamp', 0))
time_since_last = datetime.utcnow().timestamp() - last_msg_time  # ❌ FAILS
```

**Root Cause:**
- DynamoDB boto3 returns all numbers as `Decimal` type
- `datetime.utcnow().timestamp()` returns `float`
- Cannot subtract Decimal from float

**Locations to Fix:**
1. Line ~40: `get_or_create_conversation()` - time_since_last
2. Line ~2470: `engagement_prompt` handler - time_since_last
3. Line ~2490: `auto_resolve` handler - time_since_last
4. Line ~2515: approval timeout - conversation_age_days

### Error 2: Missing Table - recent-interactions ⚠️ CRITICAL
**Location:** `log_interaction_to_dynamodb()` line 1354
**Error:** `ResourceNotFoundException: Requested resource not found`

**Code:**
```python
table = dynamodb.Table('recent-interactions')  # ❌ TABLE DOESN'T EXIST
```

**Root Cause:**
- Function tries to write to `recent-interactions` table
- Table does not exist in AWS
- This is a legacy/unused function

**Verified Tables:**
- ✅ `brie-it-helpdesk-bot-interactions` (exists)
- ✅ `it-actions` (exists)
- ✅ `it-helpdesk-tickets` (exists)
- ❌ `recent-interactions` (DOES NOT EXIST)

## Complete Fix Plan

### Fix 1: Add Decimal Type Handling

**Add import at top of file:**
```python
from decimal import Decimal
```

**Add helper function after imports:**
```python
def to_float(value):
    """Convert DynamoDB Decimal to float safely"""
    if isinstance(value, Decimal):
        return float(value)
    return value
```

**Update all timestamp comparisons:**

**Location 1: get_or_create_conversation() ~line 40**
```python
last_msg_time = recent.get('last_message_timestamp', recent.get('timestamp', 0))
last_msg_time = to_float(last_msg_time)  # ADD THIS LINE
time_since_last = datetime.utcnow().timestamp() - last_msg_time
```

**Location 2: engagement_prompt handler ~line 2470**
```python
last_msg_time = item.get('last_message_timestamp', timestamp)
last_msg_time = to_float(last_msg_time)  # ADD THIS LINE
time_since_last = datetime.utcnow().timestamp() - last_msg_time
```

**Location 3: auto_resolve handler ~line 2490**
```python
last_msg_time = item.get('last_message_timestamp', timestamp)
last_msg_time = to_float(last_msg_time)  # ADD THIS LINE
time_since_last = datetime.utcnow().timestamp() - last_msg_time
```

**Location 4: approval timeout ~line 2515**
```python
timestamp_val = to_float(timestamp)  # ADD THIS LINE
conversation_age_days = (datetime.utcnow().timestamp() - timestamp_val) / 86400
```

### Fix 2: Remove or Fix recent-interactions Table Reference

**Option A: Remove the function (RECOMMENDED)**
- Function appears unused/legacy
- No calls to `log_interaction_to_dynamodb()` in main code
- Safe to comment out or remove

**Option B: Create the table**
- Not recommended - adds unnecessary complexity
- Already tracking in `brie-it-helpdesk-bot-interactions`

**Action: Comment out the function at line 1352-1370**

### Fix 3: Add Error Handling

**Wrap timestamp operations in try/except:**
```python
try:
    last_msg_time = to_float(item.get('last_message_timestamp', timestamp))
    time_since_last = datetime.utcnow().timestamp() - last_msg_time
except (TypeError, ValueError) as e:
    print(f"Error calculating time difference: {e}")
    time_since_last = 0  # Default to 0 to prevent crashes
```

## Implementation Steps

### Step 1: Create Fixed Version
```bash
cd /Users/matt/Brie-IT-Agent
git checkout main
# Apply fixes to lambda_it_bot_confluence.py
```

### Step 2: Test Locally
```python
# Test Decimal conversion
from decimal import Decimal
from datetime import datetime

def to_float(value):
    if isinstance(value, Decimal):
        return float(value)
    return value

# Test cases
timestamp = Decimal('1760472496')
current = datetime.utcnow().timestamp()
diff = current - to_float(timestamp)
print(f"Time diff: {diff} seconds")  # Should work
```

### Step 3: Deploy with Monitoring
```bash
# Create package
zip -q lambda_package.zip lambda_it_bot_confluence.py

# Deploy
aws lambda update-function-code \
  --function-name it-helpdesk-bot \
  --zip-file fileb://lambda_package.zip \
  --region us-east-1 \
  --profile AWSCorp

# Monitor immediately
aws logs tail /aws/lambda/it-helpdesk-bot \
  --follow \
  --region us-east-1 \
  --profile AWSCorp
```

### Step 4: Smoke Test
1. Send test message: "test excel issue"
2. Check CloudWatch for errors (30 seconds)
3. Verify DynamoDB entry created:
```bash
aws dynamodb scan \
  --table-name brie-it-helpdesk-bot-interactions \
  --filter-expression "outcome = :status" \
  --expression-attribute-values '{":status":{"S":"In Progress"}}' \
  --region us-east-1 \
  --profile AWSCorp \
  --max-items 1
```
4. If any errors: ROLLBACK IMMEDIATELY

## Summary

**2 Critical Bugs:**
1. ❌ Decimal/float type mismatch in 4 locations
2. ❌ Missing `recent-interactions` table

**Fixes Required:**
1. ✅ Add `from decimal import Decimal` import
2. ✅ Add `to_float()` helper function
3. ✅ Update 4 timestamp comparison locations
4. ✅ Comment out `log_interaction_to_dynamodb()` function
5. ✅ Add error handling for type conversions

**Estimated Fix Time:** 10 minutes
**Testing Time:** 5 minutes
**Total Time to Re-Deploy:** 15 minutes

## Ready to Fix?
All issues identified. Ready to implement fixes and re-deploy.
