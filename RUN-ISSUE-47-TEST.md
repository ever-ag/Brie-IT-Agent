# Issue #47 Integration Test - READY TO RUN

## Prerequisites
- ✅ Code deployed to it-helpdesk-bot (2025-10-18T14:24:29Z)
- ✅ AWS credentials configured (AWSCorp profile)
- ✅ Access to Slack workspace
- ✅ Access to IT approval channel

## Quick Test (5 minutes)

### Test 1: Invalid Group → Validation → Approval
**This is the main test for Issue #47**

1. **Open Slack** and DM the IT Helpdesk Bot

2. **Send message**: 
   ```
   add me to the clickup sso
   ```

3. **Expected Response** (within 10 seconds):
   ```
   ❓ Group Not Found

   I couldn't find a group named clickup sso.

   Did you mean one of these?

   • ClickUp
   • ClickUp Admins
   • [other similar groups]

   Please reply with the exact group name.
   ```

4. **Verify NO approval in IT channel yet** ✅ THIS IS THE KEY FIX

5. **Reply with**:
   ```
   ClickUp
   ```

6. **Expected Response**:
   ```
   ✅ Got it! Requesting access to ClickUp...
   ✅ Your sso group request has been submitted to IT for approval.
   ```

7. **Verify approval NOW appears in IT channel** ✅

8. **Check DynamoDB** (optional):
   ```bash
   aws dynamodb scan \
     --table-name it-actions \
     --filter-expression "#status = :status" \
     --expression-attribute-names '{"#status":"status"}' \
     --expression-attribute-values '{":status":{"S":"PENDING_SELECTION"}}' \
     --region us-east-1 \
     --profile AWSCorp \
     --query 'Count'
   ```
   Should be 0 (pending selection was deleted after user confirmed)

### Test 2: Valid Group → Direct Approval
**Verify we didn't break the happy path**

1. **Send message**:
   ```
   add me to the SSO AWS Corp Workspace Full
   ```

2. **Expected Response** (within 10 seconds):
   ```
   ✅ Your sso group request has been submitted to IT for approval.
   ```

3. **Verify approval appears in IT channel immediately** ✅

4. **No group selection prompt** ✅

## Monitoring Commands

### Watch CloudWatch Logs Live
```bash
aws logs tail /aws/lambda/it-helpdesk-bot \
  --follow \
  --region us-east-1 \
  --profile AWSCorp \
  --format short \
  | grep -E "Validating group|Group not found|Group validated|PENDING_SELECTION"
```

### Check Recent Validations
```bash
aws logs tail /aws/lambda/it-helpdesk-bot \
  --since 5m \
  --region us-east-1 \
  --profile AWSCorp \
  --format short \
  | grep "🔍 Validating group"
```

### Check Pending Selections
```bash
aws dynamodb scan \
  --table-name it-actions \
  --filter-expression "#status = :status" \
  --expression-attribute-names '{"#status":"status"}' \
  --expression-attribute-values '{":status":{"S":"PENDING_SELECTION"}}' \
  --region us-east-1 \
  --profile AWSCorp \
  --output table
```

### Check Conversation History
```bash
aws dynamodb scan \
  --table-name brie-it-helpdesk-bot-interactions \
  --filter-expression "contains(conversation_history, :text)" \
  --expression-attribute-values '{":text":{"S":"Group Not Found"}}' \
  --region us-east-1 \
  --profile AWSCorp \
  --query 'Items[0].conversation_history' \
  --output text \
  | jq .
```

## Success Criteria

✅ **Test 1 Pass Criteria**:
- Bot asks for clarification BEFORE sending to IT
- NO approval in IT channel until user confirms
- User can select from similar groups
- Approval sent AFTER user confirms

✅ **Test 2 Pass Criteria**:
- Valid group goes straight to approval
- No unnecessary prompts
- Approval sent immediately

## Troubleshooting

### Bot doesn't respond
- Check CloudWatch logs for errors
- Verify Lambda function is active
- Check Slack bot token is valid

### Validation takes too long (>10 seconds)
- SSM commands to AD may be slow
- Check Bespin instance (i-0dca7766c8de43f08) is running
- Check network connectivity to domain controller

### No similar groups found
- AD query may have failed
- Check SSM command output in CloudWatch
- Verify PowerShell Get-ADGroup works on Bespin

### Pending selection not working
- Check DynamoDB table 'it-actions' exists
- Verify status is 'PENDING_SELECTION' (uppercase)
- Check pending selection hasn't expired (5 min timeout)

## Next Steps After Testing

If tests pass:
1. Document results in GitHub issue #47
2. Close issue #47 with test results
3. Commit changes to git
4. Update documentation

If tests fail:
1. Check CloudWatch logs for errors
2. Document failure in GitHub issue #47
3. Debug and fix issues
4. Re-deploy and re-test
