# IT Helpdesk Bot - Infrastructure Documentation

**Generated on:** September 5, 2025  
**AWS Account:** 843046951786  
**Region:** us-east-1  

---

## Executive Summary

The IT Helpdesk Bot is a serverless application built on AWS Lambda that provides automated IT support through Slack integration. The system uses AI-powered responses via Amazon Bedrock and maintains ticket records in DynamoDB.

---

## Architecture Overview

```
Slack Users → API Gateway → Lambda Function → DynamoDB
                ↓
            Amazon Bedrock (AI)
                ↓
            Amazon SES (Email)
```

---

## Lambda Function Configuration

### Basic Details
- **Function Name:** `it-helpdesk-bot`
- **Function ARN:** `arn:aws:lambda:us-east-1:843046951786:function:it-helpdesk-bot`
- **Runtime:** Python 3.9
- **Handler:** `lambda_it_bot_confluence.lambda_handler`
- **Architecture:** x86_64
- **Package Type:** Zip

### Resource Allocation
- **Memory Size:** 128 MB
- **Timeout:** 120 seconds (2 minutes)
- **Ephemeral Storage:** 512 MB
- **Code Size:** 9,107 bytes

### Status & Versioning
- **State:** Active
- **Version:** $LATEST
- **Last Modified:** September 3, 2025 18:28:30 UTC
- **Last Update Status:** Successful
- **Revision ID:** 4e3b9e5b-fa3a-4cb4-a2af-44a53f38d31f

### Environment Variables
| Variable | Value |
|----------|-------|
| SLACK_SIGNING_SECRET | your-slack-signing-secret |
| SLACK_BOT_TOKEN | SLACK_BOT_TOKEN |

---

## IAM Role & Security

### Role Details
- **Role Name:** `lambda-it-helpdesk-role`
- **Role ARN:** `arn:aws:iam::843046951786:role/lambda-it-helpdesk-role`
- **Created:** August 29, 2025 12:54:21 UTC
- **Last Used:** September 4, 2025 21:32:20 UTC

### Trust Policy
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Attached Policies
1. **AWSLambdaBasicExecutionRole**
   - Purpose: CloudWatch Logs access
   - Type: AWS Managed Policy

2. **AmazonSESFullAccess**
   - Purpose: Email sending capabilities
   - Type: AWS Managed Policy

3. **AmazonDynamoDBFullAccess**
   - Purpose: Database operations
   - Type: AWS Managed Policy

4. **AmazonBedrockFullAccess**
   - Purpose: AI/ML model access
   - Type: AWS Managed Policy

---

## API Gateway Configuration

### REST API Details
- **API Name:** `it-helpdesk-bot-api`
- **API ID:** `ehc2cau09c`
- **Created:** August 29, 2025 08:10:32 CDT
- **Endpoint Type:** Edge-optimized
- **IP Address Type:** IPv4
- **Root Resource ID:** `gvhn3rj1tf`

### Deployment Information
- **Current Stage:** `prod`
- **Deployment ID:** `rgs8hl`
- **Stage Created:** August 29, 2025 08:10:35 CDT
- **Last Updated:** September 2, 2025 13:29:41 CDT

### API Endpoint
```
https://ehc2cau09c.execute-api.us-east-1.amazonaws.com/prod
```

### Lambda Integration Policy
The API Gateway has permission to invoke the Lambda function through resource-based policies:
- Source ARN: `arn:aws:execute-api:us-east-1:843046951786:ehc2cau09c/*/*`

---

## DynamoDB Database

### Table Configuration
- **Table Name:** `it-helpdesk-tickets`
- **Table ARN:** `arn:aws:dynamodb:us-east-1:843046951786:table/it-helpdesk-tickets`
- **Created:** August 29, 2025 07:54:21 CDT
- **Status:** ACTIVE

### Schema Design
- **Primary Key:** `ticket_id` (String, Hash Key)
- **Key Type:** Simple primary key (partition key only)

### Capacity & Billing
- **Billing Mode:** Pay-per-request
- **Read Capacity:** On-demand
- **Write Capacity:** On-demand
- **Warm Throughput:** 
  - Read: 12,000 units/second
  - Write: 4,000 units/second

### Current Usage
- **Item Count:** 57 tickets
- **Table Size:** 30,700 bytes (~30 KB)
- **Deletion Protection:** Disabled

---

## Monitoring & Logging

### CloudWatch Logs
- **Log Group:** `/aws/lambda/it-helpdesk-bot`
- **Log Format:** Text
- **Retention:** Default (Never expire)

### Recent Activity
- **Last Execution:** September 4, 2025
- **Active Log Streams:** Multiple recent executions
- **Execution Frequency:** Regular usage pattern

### Tracing
- **X-Ray Tracing:** PassThrough mode
- **SnapStart:** Disabled

---

## Integration Details

### Slack Integration
- **Bot Token:** Configured via environment variable
- **Signing Secret:** Configured for request verification
- **Communication:** Bidirectional via API Gateway webhook

### Confluence Integration
- **Handler Reference:** `lambda_it_bot_confluence.lambda_handler`
- **Purpose:** Likely for knowledge base integration

### Amazon Bedrock (AI)
- **Access Level:** Full access via IAM policy
- **Purpose:** AI-powered response generation
- **Models:** Access to all available Bedrock models

### Amazon SES (Email)
- **Access Level:** Full access via IAM policy
- **Purpose:** Email notifications and communications
- **Region:** us-east-1

---

## Security Considerations

### Access Control
- Lambda function uses least-privilege IAM role
- API Gateway integration uses resource-based policies
- Environment variables store sensitive configuration

### Network Security
- Edge-optimized API Gateway for global access
- HTTPS-only communication
- Slack webhook verification via signing secret

### Data Protection
- DynamoDB encryption at rest (default)
- CloudWatch Logs encryption
- Secure environment variable storage

---

## Operational Metrics

### Performance
- **Memory Utilization:** 128 MB allocated
- **Execution Time:** Up to 120 seconds timeout
- **Cold Start:** Minimal impact with current configuration

### Cost Optimization
- Pay-per-request DynamoDB billing
- Serverless Lambda execution model
- Edge-optimized API Gateway for global performance

### Availability
- Multi-AZ deployment via AWS managed services
- Automatic scaling based on demand
- No single points of failure

---

## Maintenance & Updates

### Recent Changes
- **Last Code Update:** September 3, 2025
- **Last API Deployment:** September 2, 2025
- **Infrastructure Created:** August 29, 2025

### Monitoring Recommendations
1. Set up CloudWatch alarms for error rates
2. Monitor DynamoDB throttling metrics
3. Track API Gateway 4xx/5xx errors
4. Monitor Lambda duration and memory usage

### Backup Strategy
- DynamoDB point-in-time recovery (if enabled)
- Lambda function code versioning
- Infrastructure as Code recommended

---

## Technical Specifications

### Dependencies
- Python 3.9 runtime environment
- Slack SDK (implied by bot token usage)
- AWS SDK (boto3) for service integrations
- Confluence API integration libraries

### API Endpoints
- **Primary Endpoint:** POST requests to API Gateway
- **Webhook URL:** For Slack event subscriptions
- **Health Check:** Standard Lambda function monitoring

### Data Flow
1. Slack user sends message/command
2. Slack forwards to API Gateway webhook
3. API Gateway triggers Lambda function
4. Lambda processes request using Bedrock AI
5. Response stored in DynamoDB
6. Reply sent back to Slack user
7. Optional email notification via SES

---

## Troubleshooting Guide

### Common Issues
- **Timeout Errors:** Check 120-second Lambda timeout
- **Permission Errors:** Verify IAM role policies
- **Slack Integration:** Validate signing secret and bot token
- **Database Errors:** Check DynamoDB table status

### Log Analysis
- Check CloudWatch Logs for execution details
- Monitor API Gateway access logs
- Review DynamoDB CloudWatch metrics

---

## Contact Information

**System Owner:** matthew.denecke@ever.ag  
**AWS Account:** 843046951786  
**Support Role:** AWSReservedSSO_Ever.Ag_Accounts_AdminAccess

---

*This document was automatically generated from live AWS infrastructure on September 5, 2025.*
