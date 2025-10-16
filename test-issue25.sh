#!/bin/bash
# Test for Issue #25 - Engagement prompts when resuming conversations

echo "Testing Issue #25 Fix: Engagement prompts for resumed conversations"
echo "======================================================================"
echo ""

# Check if schedule_auto_resolve is called after conversation resumption
echo "Checking if schedule_auto_resolve() is called after resumption..."
OCCURRENCES=$(grep -c "schedule_auto_resolve(old_interaction_id" ~/Brie-IT-Agent/lambda_it_bot_confluence.py)

if [ "$OCCURRENCES" -ge 2 ]; then
    echo "✓ PASS: schedule_auto_resolve() is called in $OCCURRENCES locations"
    grep -n "schedule_auto_resolve(old_interaction_id" ~/Brie-IT-Agent/lambda_it_bot_confluence.py
else
    echo "✗ FAIL: schedule_auto_resolve() not found after conversation resumption"
    exit 1
fi

echo ""
echo "✓ Code fix verified successfully"
echo ""
echo "Manual Test Instructions:"
echo "========================="
echo "1. Send: 'my laptop is slow'"
echo "2. Wait 20 minutes for timeout"
echo "3. Send: 'my laptop is still slow'"
echo "4. Click 'Yes' to resume conversation"
echo "5. Verify engagement prompts at 5min, 10min, 15min"
