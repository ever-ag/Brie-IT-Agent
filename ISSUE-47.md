# Issue #47: SSO Group Validation Should Happen BEFORE Approval

## Problem
Group name validation happens AFTER IT approval, wasting IT time on invalid requests.

## Current Flow (WRONG)
1. User: "add me to the clickup sso"
2. Bot: "Request sent to IT for approval"
3. IT: Approves
4. Bot: "Group not found. Did you mean ClickUp?"
5. Bot: "There was an issue processing your request"

## Desired Flow (CORRECT)
1. User: "add me to the clickup sso"
2. Bot: "Group not found. Did you mean ClickUp?"
3. User: "ClickUp"
4. Bot: "Request sent to IT for approval"
5. IT: Approves
6. Bot: "✅ Request completed!"

## Root Cause
The `handle_sop_sso_request` function calls `it-approval-system` immediately without validating the group name first. The validation happens later in `brie-ad-group-manager` after IT has already approved.

## Solution
Move group validation to happen BEFORE creating the approval request:
1. Extract group name from user message
2. Query AD to validate group exists
3. If not found, show similar groups and wait for user confirmation
4. Only after group is confirmed, send to IT for approval

## Files Involved
- `lambda_it_bot_fixed.py` - `handle_sop_sso_request()` function
- `brie-ad-group-manager.py` - Group validation logic

## Test Case
```
User: "add me to the clickup sso"
Expected: Bot asks "Did you mean ClickUp?" BEFORE IT approval
Actual: IT approves first, THEN bot asks for clarification
```

## Priority
High - wastes IT staff time and creates poor user experience

## Created
October 18, 2025 - 09:17 AM CST

## GitHub Issue
https://github.com/ever-ag/Brie-IT-Agent/issues/47
