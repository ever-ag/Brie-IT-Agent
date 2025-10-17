# IT AUTOMATION SYSTEM RECOVERY CONTEXT

## CURRENT STATUS
Building unified IT automation system to replace 3 separate functions

## PROBLEM SOLVED
- SSO automation was broken/inconsistent 
- Multiple competing code paths in lambda_it_bot_confluence.py
- Performance issues with Slack API calls
- Need unified system for 4 request types

## SOLUTION
Unified system handling:
1. Security Groups (SSO access in AD)
2. Other Groups (AD or Office 365) 
3. Email Distribution Lists (AD or Office 365)
4. Shared Mailboxes (Office 365)

## KEY COMPONENTS
- AI categorization of requests
- Fuzzy search for matching
- Unified approval workflow in channel C09KB40PL9J
- Member validation (already member check)
- 3-day timeout → auto-create ticket
- Complete database logging for dashboard

## CURRENT FUNCTIONS TO REPLACE
- it-helpdesk-bot (main bot with broken SSO logic)
- it-approval-system (working - keep this)
- it-action-processor (partially broken)

## KEY INFO
- **APPROVAL CHANNEL:** C09KB40PL9J
- **GITHUB REPO:** https://github.com/matthewdenecke/it-automation-system
- **GITHUB ISSUE:** https://github.com/matthewdenecke/it-automation-system/issues/1
- **AWS PROFILE:** awscorp
- **REGION:** us-east-1

## NEXT STEPS
Build unified system with incremental commits to GitHub
