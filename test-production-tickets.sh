#!/bin/bash

echo "=========================================="
echo "PRODUCTION TICKET VALIDATION"
echo "Date: $(date)"
echo "=========================================="
echo ""

# Get last 20 production tickets
echo "Fetching last 20 production tickets..."
TICKETS=$(aws dynamodb scan \
  --profile AWSCorp \
  --region us-east-1 \
  --table-name brie-it-helpdesk-bot-interactions \
  --limit 20 \
  --output json 2>/dev/null)

if [ $? -ne 0 ]; then
  echo "ERROR: Failed to query DynamoDB"
  exit 1
fi

TICKET_COUNT=$(echo "$TICKETS" | jq '.Items | length')
echo "Retrieved $TICKET_COUNT tickets"
echo ""

# TS011-T001: Recent Ticket Analysis
echo "TS011-T001: Recent Ticket Analysis"
echo "-----------------------------------"

VALID_TYPES=0
VALID_OUTCOMES=0
VALID_HISTORY=0
VALID_TIMESTAMPS=0

for i in $(seq 0 $((TICKET_COUNT-1))); do
  TYPE=$(echo "$TICKETS" | jq -r ".Items[$i].interaction_type.S // empty")
  OUTCOME=$(echo "$TICKETS" | jq -r ".Items[$i].outcome.S // empty")
  HISTORY=$(echo "$TICKETS" | jq -r ".Items[$i].conversation_history.S // empty")
  TIMESTAMP=$(echo "$TICKETS" | jq -r ".Items[$i].timestamp.N // empty")
  
  [ -n "$TYPE" ] && ((VALID_TYPES++))
  [ -n "$OUTCOME" ] && ((VALID_OUTCOMES++))
  [ -n "$HISTORY" ] && [ "$HISTORY" != "[]" ] && ((VALID_HISTORY++))
  [ -n "$TIMESTAMP" ] && ((VALID_TIMESTAMPS++))
done

echo "Valid interaction_type: $VALID_TYPES/$TICKET_COUNT"
echo "Valid outcome: $VALID_OUTCOMES/$TICKET_COUNT"
echo "Valid conversation_history: $VALID_HISTORY/$TICKET_COUNT"
echo "Valid timestamp: $VALID_TIMESTAMPS/$TICKET_COUNT"

if [ $VALID_TYPES -eq $TICKET_COUNT ] && [ $VALID_OUTCOMES -eq $TICKET_COUNT ] && [ $VALID_HISTORY -eq $TICKET_COUNT ] && [ $VALID_TIMESTAMPS -eq $TICKET_COUNT ]; then
  echo "Status: ✓ PASS"
else
  echo "Status: ✗ FAIL"
fi
echo ""

# TS011-T002: Categorization Accuracy
echo "TS011-T002: Categorization Accuracy"
echo "------------------------------------"
echo "Interaction Type Distribution:"
echo "$TICKETS" | jq -r '.Items[].interaction_type.S' | sort | uniq -c | sort -rn
echo ""

# TS011-T003: Approval Workflow Completion
echo "TS011-T003: Approval Workflow Completion"
echo "-----------------------------------------"

STUCK_APPROVALS=$(aws dynamodb scan \
  --profile AWSCorp \
  --region us-east-1 \
  --table-name brie-it-helpdesk-bot-interactions \
  --filter-expression "awaiting_approval = :true" \
  --expression-attribute-values '{":true":{"BOOL":true}}' \
  --output json 2>/dev/null | jq '.Items | length')

if [ "$STUCK_APPROVALS" = "0" ]; then
  echo "Stuck approvals (awaiting_approval=true): 0"
  echo "Status: ✓ PASS - No stuck approvals"
else
  echo "Stuck approvals (awaiting_approval=true): $STUCK_APPROVALS"
  echo "Status: ⚠️ WARNING - Manual review required"
fi
echo ""

# TS011-T004: Self-Service Success Rate
echo "TS011-T004: Self-Service Success Rate"
echo "--------------------------------------"

TOTAL=$(echo "$TICKETS" | jq '.Items | length')
SELF_SERVICE=$(echo "$TICKETS" | jq '[.Items[].outcome.S] | map(select(. == "Self-Service Solution")) | length')
TICKET_CREATED=$(echo "$TICKETS" | jq '[.Items[].outcome.S] | map(select(. == "Ticket Created")) | length')
AWAITING=$(echo "$TICKETS" | jq '[.Items[].outcome.S] | map(select(. == "Awaiting Approval")) | length')
RESOLVED=$(echo "$TICKETS" | jq '[.Items[].outcome.S] | map(select(. == "Resolved by Brie")) | length')

SELF_SERVICE_PCT=$(awk "BEGIN {printf \"%.1f\", ($SELF_SERVICE/$TOTAL)*100}")
TICKET_PCT=$(awk "BEGIN {printf \"%.1f\", ($TICKET_CREATED/$TOTAL)*100}")
AWAITING_PCT=$(awk "BEGIN {printf \"%.1f\", ($AWAITING/$TOTAL)*100}")
RESOLVED_PCT=$(awk "BEGIN {printf \"%.1f\", ($RESOLVED/$TOTAL)*100}")

echo "Self-Service Solutions: $SELF_SERVICE ($SELF_SERVICE_PCT%)"
echo "Tickets Created: $TICKET_CREATED ($TICKET_PCT%)"
echo "Awaiting Approval: $AWAITING ($AWAITING_PCT%)"
echo "Resolved by Brie: $RESOLVED ($RESOLVED_PCT%)"
echo ""

if (( $(echo "$SELF_SERVICE_PCT >= 30" | bc -l) )); then
  echo "Self-Service rate: ✓ PASS (>= 30%)"
else
  echo "Self-Service rate: ⚠️ WARNING (< 30%)"
fi

if (( $(echo "$TICKET_PCT <= 50" | bc -l) )); then
  echo "Ticket creation rate: ✓ PASS (<= 50%)"
else
  echo "Ticket creation rate: ⚠️ WARNING (> 50%)"
fi
echo ""

# TS011-T005: Response Quality Check
echo "TS011-T005: Response Quality Check"
echo "-----------------------------------"
echo "Status: MANUAL REVIEW REQUIRED"
echo "Action: Review 5 random tickets for response quality"
echo ""
echo "Sample tickets for manual review:"
echo "$TICKETS" | jq -r '.Items[0:5] | .[] | "- \(.interaction_id.S): \(.description.S)"'
echo ""

echo "=========================================="
echo "PRODUCTION VALIDATION COMPLETE"
echo "=========================================="
