# Brie IT Agent - Complete Backup
**Date:** October 22, 2025
**Tag:** v1.0.0-stable-2025-10-22

## What's Included
- Complete git repository with all history
- All 4 deployed Lambda function ZIP files
- All source code and configuration files

## Tested and Working Features
✅ SSO Group Access: "add me to sso aws corp admin"
✅ Distribution List Access: "add me to employees dl" → LocalEmployees
✅ Shared Mailbox Access: "Add me to the itsupport@ever.ag shared mailbox"
✅ General IT Support: "My laptop is slow"

## Restore Instructions

### 1. Restore Git Repository
```bash
cd ~/Brie-IT-Agent-Backup-2025-10-22
git checkout v1.0.0-stable-2025-10-22
```

### 2. Deploy Lambda Functions
```bash
# it-helpdesk-bot
aws lambda update-function-code --function-name it-helpdesk-bot \
  --zip-file fileb://lambda-functions/it-helpdesk-bot.zip \
  --profile AWSCorp --region us-east-1

# it-approval-system
aws lambda update-function-code --function-name it-approval-system \
  --zip-file fileb://lambda-functions/it-approval-system.zip \
  --profile AWSCorp --region us-east-1

# brie-infrastructure-connector
aws lambda update-function-code --function-name brie-infrastructure-connector \
  --zip-file fileb://lambda-functions/brie-infrastructure-connector.zip \
  --profile AWSCorp --region us-east-1

# brie-ad-group-manager
aws lambda update-function-code --function-name brie-ad-group-manager \
  --zip-file fileb://lambda-functions/brie-ad-group-manager.zip \
  --profile AWSCorp --region us-east-1
```

### 3. Verify Deployment
Check Lambda LastModified dates match:
- it-helpdesk-bot: 2025-10-22T18:16:59Z
- it-approval-system: 2025-10-22T16:34:45Z
- brie-infrastructure-connector: 2025-10-22T18:44:31Z

## Known Issues (Non-Blocking)
- Issue #91: DL IT channel notifications not posting
- Issue #92: Duplicate messages for shared mailbox requests
