# Issue #47 Test Plan: Pre-Approval Group Validation

## Summary
SSO group validation now happens BEFORE IT approval, not after. This prevents wasting IT staff time approving invalid requests.

## Code Changes
- Added `validate_sso_group()` function in `lambda_it_bot_fixed.py` (line 1838)
- Modified `trigger_automation_workflow()` to validate groups before creating approvals (line 1964)
- Validation uses SSM to query Active Directory via PowerShell
- If group not found, searches for similar groups and stores pending selection
- User must confirm correct group before approval is sent to IT

## Deployment
- **Function**: it-helpdesk-bot
- **Deployed**: 2025-10-18T14:24:29Z
- **Handler**: lambda_it_bot_fixed.lambda_handler
- **Region**: us-east-1

## Test Cases

### Test 1: Invalid Group Name (Primary Test Case)
**Scenario**: User requests access to non-existent group

**Steps**:
1. Send to Slack bot: `add me to the clickup sso`
2. Bot extracts: `group_name = "clickup sso"`
3. Bot validates: `validate_sso_group("clickup sso")`
4. AD returns: NOT_FOUND
5. Bot searches: `Get-ADGroup -Filter "Name -like '*clickup*'"`
6. Bot finds similar: `["ClickUp", "ClickUp Admins", ...]`
7. Bot stores pending selection in DynamoDB `it-actions` table
8. Bot responds: "❓ Group Not Found. Did you mean one of these?"

**Expected Results**:
- ✅ Bot asks for clarification
- ✅ NO approval sent to IT channel yet
- ✅ Pending selection stored in DynamoDB
- ✅ User can reply with correct group name

**Verification**:
```bash
# Check DynamoDB for pending selection
aws dynamodb scan \
  --table-name it-actions \
  --filter-expression "#status = :status" \
  --expression-attribute-names '{"#status":"status"}' \
  --expression-attribute-values '{":status":{"S":"PENDING_SELECTION"}}' \
  --region us-east-1 \
  --profile AWSCorp

# Check CloudWatch logs
aws logs tail /aws/lambda/it-helpdesk-bot \
  --since 5m \
  --region us-east-1 \
  --profile AWSCorp \
  | grep "Validating group"
```

### Test 2: User Confirms Correct Group
**Scenario**: User replies with correct group name from suggestions

**Steps**:
1. (Following Test 1) User replies: `ClickUp`
2. Bot checks pending selection in DynamoDB
3. Bot matches "ClickUp" to similar_groups list
4. Bot validates: `validate_sso_group("ClickUp")`
5. AD returns: FOUND
6. Bot creates approval
7. Bot sends to IT channel

**Expected Results**:
- ✅ Bot confirms: "Got it! Requesting access to ClickUp..."
- ✅ Approval NOW sent to IT channel
- ✅ Pending selection deleted from DynamoDB
- ✅ Conversation marked as "Awaiting Approval"

### Test 3: Valid Group Name (Direct Approval)
**Scenario**: User requests access to valid, existing group

**Steps**:
1. Send to Slack bot: `add me to the SSO AWS Corp Workspace Full`
2. Bot extracts: `group_name = "SSO AWS Corp Workspace Full"`
3. Bot validates: `validate_sso_group("SSO AWS Corp Workspace Full")`
4. AD returns: FOUND
5. Bot creates approval immediately
6. Bot sends to IT channel

**Expected Results**:
- ✅ Bot responds: "Your request has been submitted to IT for approval"
- ✅ Approval sent to IT channel immediately
- ✅ NO pending selection created
- ✅ Conversation marked as "Awaiting Approval"

### Test 4: No Similar Groups Found
**Scenario**: User requests completely invalid group name

**Steps**:
1. Send to Slack bot: `add me to the xyzabc123 group`
2. Bot validates: `validate_sso_group("xyzabc123")`
3. AD returns: NOT_FOUND
4. Bot searches: No similar groups found
5. Bot responds with error

**Expected Results**:
- ✅ Bot responds: "Group Not Found. Please contact IT for assistance"
- ✅ NO approval sent to IT
- ✅ NO pending selection created
- ✅ User can start new request

### Test 5: Validation Error Handling
**Scenario**: AD query fails or times out

**Steps**:
1. (Simulate by temporarily breaking AD connection)
2. Bot validates group
3. SSM command fails or times out
4. Bot catches exception

**Expected Results**:
- ✅ Bot returns error with empty similar_groups
- ✅ Bot responds: "Group Not Found. Please contact IT"
- ✅ No crash or unhandled exception
- ✅ Error logged to CloudWatch

## Comparison: Before vs After

### BEFORE (Issue #47 - BROKEN)
```
User: "add me to the clickup sso"
→ Bot: "Request sent to IT for approval" ❌
→ IT: Approves ❌ (wasted time)
→ brie-ad-group-manager: Group not found
→ Bot: "Group not found. Did you mean ClickUp?" ❌ (too late!)
→ Bot: "There was an issue processing your request"
```

### AFTER (Issue #47 - FIXED)
```
User: "add me to the clickup sso"
→ Bot: "Group not found. Did you mean ClickUp?" ✅
→ User: "ClickUp"
→ Bot: "Request sent to IT for approval" ✅
→ IT: Approves ✅ (valid request)
→ Bot: "✅ Request completed!"
```

## Success Criteria
- ✅ Invalid group names prompt for clarification BEFORE IT approval
- ✅ Valid group names go straight to IT approval
- ✅ User can select from similar groups
- ✅ No approvals sent for invalid groups
- ✅ IT staff only sees valid, confirmed requests
- ✅ Existing functionality not broken (DL requests, mailbox requests, etc.)

## Rollback Plan
If issues occur:
1. Revert to previous version: `lambda_it_bot_fixed.py` (before validation changes)
2. Deploy previous version
3. Document issues in GitHub issue #47
4. Re-test and fix

## Notes
- Validation adds ~4-6 seconds to request processing (2 SSM commands)
- This is acceptable tradeoff for preventing invalid approvals
- Pending selections expire after 5 minutes (existing logic)
- Only affects SSO group requests, not DL or mailbox requests
