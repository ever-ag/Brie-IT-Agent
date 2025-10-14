# Image Upload Bug Analysis - Issue #12

## Problem Statement
Bot appears to not process images uploaded by users in Slack conversations.

**User Report:**
- Conversation: 10/14/2025, 6:55:06 PM
- User: Matthew Denecke
- Message: "my aws workspace is slow"
- Status: In Progress
- Issue: User uploaded image but bot didn't acknowledge it

## Code Analysis

### Current Implementation

The bot **DOES** have image processing capability:

1. **Image Detection** (lines 1910-1970)
   - Checks `files` array in Slack event
   - Checks `file_share` subtype
   - Checks `attachments` array
   - Looks for multiple URL fields: `thumb_720`, `thumb_480`, `thumb_360`, `permalink_public`, `url_private_download`, `url_private`

2. **Image Analysis** (lines 1477-1585)
   - Function: `analyze_image_with_claude(image_url, user_message)`
   - Downloads image from Slack using bot token
   - Converts to base64
   - Sends to Claude Vision API (Bedrock)
   - Extracts technical information (speed tests, errors, configs)

3. **User Notification** (lines 2520-2550)
   - Sends "🤔 Still analyzing your image..." message
   - Processes image with Claude Vision
   - Includes analysis in bot response

### Root Cause Analysis

**Possible Issues:**

1. **Slack Event Subscription Missing**
   - Bot may not be subscribed to `file_shared` events
   - Check Slack App settings → Event Subscriptions
   - Required events: `message.channels`, `message.im`, `file_shared`

2. **Image URL Access Permissions**
   - Slack private URLs require bot token authentication
   - Bot token may lack `files:read` scope
   - Check Slack App settings → OAuth & Permissions
   - Required scopes: `files:read`, `files:write`

3. **Timing Issue**
   - Image upload and message may arrive as separate events
   - Bot processes message before image event arrives
   - Need to check if events are being received in correct order

4. **Subtype Filtering**
   - Line 1867: Bot filters out `bot_message`, `message_changed`, `message_deleted`
   - `file_share` subtype might be getting filtered incorrectly

## Testing Required

### 1. Check Slack Event Logs
```bash
# Check Lambda logs for image upload event
aws logs filter-log-events \
  --profile AWSCorp \
  --region us-east-1 \
  --log-group-name /aws/lambda/it-helpdesk-bot \
  --start-time $(date -u -d '2025-10-14 18:55:00' +%s)000 \
  --filter-pattern "files"
```

### 2. Check Slack App Configuration
- Go to https://api.slack.com/apps
- Select "Brie IT Helpdesk Bot"
- Check Event Subscriptions:
  - ✓ `message.channels`
  - ✓ `message.im`
  - ✓ `file_shared` (CRITICAL)
- Check OAuth Scopes:
  - ✓ `files:read` (CRITICAL)
  - ✓ `files:write`

### 3. Test Image Upload
1. Send message: "test image upload"
2. Upload screenshot
3. Check Lambda logs for:
   - "Found files array"
   - "File share detected"
   - "Image detected with URL"
   - "Attempting to analyze image"

## Recommended Fix

### Option 1: Add Missing Slack Scopes (Most Likely)
1. Add `files:read` scope to Slack bot
2. Add `file_shared` event subscription
3. Reinstall bot to workspace

### Option 2: Handle Separate File Events
If images arrive as separate events, add handler:
```python
if slack_event['type'] == 'file_shared':
    file_id = slack_event.get('file_id')
    user_id = slack_event.get('user_id')
    # Retrieve file info and associate with recent message
```

### Option 3: Improve Event Logging
Add more detailed logging to diagnose:
```python
print(f"Event type: {slack_event.get('type')}")
print(f"Event subtype: {slack_event.get('subtype')}")
print(f"Files present: {bool(slack_event.get('files'))}")
print(f"File object: {slack_event.get('file')}")
```

## Impact Assessment

**Current State:**
- Image processing code exists and is functional
- Issue is likely configuration or event delivery
- Bot gracefully handles missing images with fallback messages

**User Impact:**
- Users cannot share screenshots for troubleshooting
- Reduces bot effectiveness for visual issues (speed tests, error messages)
- Forces users to describe images verbally

**Priority:** Medium
- Has workaround (describe image or create ticket)
- Affects user experience but not critical functionality
- Code is ready, likely just needs configuration fix

## Next Steps

1. **Immediate:** Check Lambda logs for the specific conversation (10/14/2025, 6:55:06 PM)
2. **Verify:** Slack app has `files:read` scope and `file_shared` event subscription
3. **Test:** Upload image in test conversation and monitor logs
4. **Fix:** Add missing scopes/events if needed
5. **Validate:** Confirm image analysis works end-to-end

## Code Quality Notes

**Strengths:**
- Comprehensive image detection (3 methods)
- Graceful error handling with user-friendly messages
- Claude Vision integration for technical analysis
- Proper authentication with Slack bot token

**Potential Improvements:**
- Add retry logic for image download failures
- Cache image analysis to avoid re-processing
- Support multiple images in single message
- Add image size/format validation before processing
