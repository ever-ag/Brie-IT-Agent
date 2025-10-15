# Restore Point: Pre-Bug #14 Timeout Fix

**Created:** 2025-10-14 15:01 CST
**Purpose:** Full restore point before implementing major conversation timeout workflow changes

## Git Restore Point

**Tag:** `pre-bug14-timeout-fix`

### To restore from this point:
```bash
git checkout pre-bug14-timeout-fix
git checkout -b restore-from-pre-bug14
# Deploy this version to Lambda
```

## Local Backup

**File:** `lambda_it_bot_confluence.py.backup-20251014-150109`

### To restore from local backup:
```bash
cp lambda_it_bot_confluence.py.backup-20251014-150109 lambda_it_bot_confluence.py
# Deploy to Lambda
```

## Current State Before Changes

### Timeout Configuration
- Regular conversation timeout: 15 minutes (from conversation START time)
- Approval timeout: 7 days
- No engagement prompts
- No conversation resumption logic

### Known Issues Being Fixed
1. Timeout checks conversation start time instead of last message time
2. Creates duplicate conversations after timeout
3. No engagement prompts during inactivity
4. No proper timeout messages logged to conversation history

### Files Modified in Bug #14
- `lambda_it_bot_confluence.py` - Main Lambda function

### DynamoDB Tables (No Schema Changes)
- `brie-it-interactions` - Conversation tracking
- `it-actions` - Approval requests
- `it-helpdesk-tickets` - Ticket storage

## Deployment Restore

If deployed Lambda needs rollback:
```bash
# 1. Restore code from git tag
git checkout pre-bug14-timeout-fix

# 2. Deploy to Lambda
cd /Users/matt/Brie-IT-Agent
zip -r lambda_package.zip lambda_it_bot_confluence.py
aws lambda update-function-code \
  --function-name it-helpdesk-bot \
  --zip-file fileb://lambda_package.zip \
  --region us-east-1

# 3. Verify deployment
aws lambda get-function --function-name it-helpdesk-bot --region us-east-1
```

## Testing After Restore
1. Send test message to bot
2. Verify conversation starts normally
3. Check DynamoDB for interaction record
4. Verify no errors in CloudWatch logs

## Related Issues
- Issue #14: Bug: Conversation timeout creates duplicates and lacks engagement prompts
- Issue #15: Enhancement: Implement ticket creation for 5-day approval timeouts (NOT included in this fix)
