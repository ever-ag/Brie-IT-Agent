# Brie IT Agent

Automated IT helpdesk bot using AWS Lambda, Claude AI, and Microsoft Graph API to process IT support emails and provide intelligent responses.

## Overview

Brie IT Agent is an automated email processing system that:
- Monitors brieitagent@ever.ag for incoming IT support requests
- Analyzes email content and image attachments using Claude Vision
- Applies 15 detection steps covering 95-98% of IT support scenarios
- Generates context-aware responses or routes to helpdesk
- Integrates with Slack for notifications and escalations

## System Architecture

- **Platform**: AWS Lambda (Python 3.12)
- **AI**: Amazon Bedrock (Claude 3.5 Sonnet)
- **Email**: Microsoft Graph API
- **Image Analysis**: Claude Vision + AWS Textract (fallback)
- **Notifications**: Slack API
- **Orchestration**: AWS Step Functions

## Key Components

### Core Lambda Functions
- `brie-mailbox-poller.py` - Main email processing engine (136KB)
- `brie-infrastructure-connector.py` - AWS infrastructure integration
- `brie-ad-group-manager.py` - Active Directory group management
- `brie-o365-integration.py` - Microsoft 365 integration

### Slack Bots
- `slack-it-bot.py` - Interactive Slack IT support bot
- `slack-it-bot-with-tickets.py` - Ticket tracking integration
- `simple-slack-it-bot.py` - Lightweight Slack bot

### Step Functions
- `brie-step-functions.json` - Main workflow orchestration
- `brie-ticket-processor-updated.json` - Ticket processing workflow

### Documentation
- `brie_it_agent_summary.txt` - Complete system documentation
- `brie-stepfunctions-workflow.pdf` - Visual workflow diagram
- `brie_image_processing_documentation.pdf` - Image analysis guide
- `it-helpdesk-bot-report.md` - Implementation report

### Dashboards & Reports
- `brie-it-helpdesk-bot-dashboard.html` - Monitoring dashboard
- `brie_regression_test_report.html` - Test results
- `brie_25_test_scenarios.html` - Test scenarios

## Detection Steps

The system processes emails through 15 prioritized detection steps:

1. **Automated System Emails** - Prevent bot loops
2. **Ever.Ag Welcome Emails** - Portal migration handling
3. **New Employee Welcome** - Onboarding routing
4. **Distribution List Inquiries** - Group membership requests
5. **Microsoft Access Denied** - Auth/permission issues
6. **Daily Admin Tasks** - Routine noise removal
7. **Onboarding/Offboarding** - Employee lifecycle
8. **Email Forwarding** - Mailbox configuration
9. **International Travel** - Security/compliance
10. **Account Creation** - User provisioning
11. **Security Alerts** - Critical notifications
12. **Windows Updates** - Patch guidance
13. **Hardware Requests** - Equipment requests
14. **Software Licensing** - Paid software approval
15. **Access Requests** - Smart routing based on specificity

## Image Analysis

- **Primary**: Claude Vision (95-98% accuracy, ~$3/1000 images)
- **Fallback**: AWS Textract (80% accuracy, ~$1.50/1000 images)
- **Supported Formats**: PNG, JPG, JPEG, GIF, BMP

## Performance

- **Coverage**: 95-98% of IT support scenarios
- **Processing Time**: 1-15 seconds (depending on images)
- **Memory**: 256 MB
- **Timeout**: 300 seconds
- **Trigger**: Every minute

## Setup & Deployment

See individual component files for specific deployment instructions.

### Prerequisites
- AWS Account with Lambda, Bedrock, Step Functions access
- Microsoft 365 tenant with Graph API permissions
- Slack workspace with bot token
- Python 3.12 runtime

## Team

Maintained by Ever.Ag IT Team

## Last Updated

October 2025
