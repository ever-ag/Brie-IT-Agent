# SOC2 Compliance Documentation

## Overview
This document outlines SOC2 compliance measures for the Brie IT Agent system.

## Security Controls

### 1. Access Control (CC6.1, CC6.2)
- AWS IAM roles with least privilege access
- Microsoft Graph API with delegated permissions
- Slack bot tokens with minimal required scopes
- No hardcoded credentials in source code

### 2. Data Encryption (CC6.7)
- **At Rest**: AWS Lambda environment variables encrypted with KMS
- **In Transit**: TLS 1.2+ for all API communications
  - Microsoft Graph API (HTTPS)
  - Slack API (HTTPS)
  - AWS Bedrock API (HTTPS)

### 3. Audit Logging (CC7.2)
- CloudWatch Logs for all Lambda executions
- Conversation logging for support interactions
- Email processing audit trail
- Slack notification logging

### 4. Change Management (CC8.1)
- Git version control for all code changes
- CHANGELOG.md for tracking modifications
- Pull request reviews required
- Automated testing before deployment

### 5. Monitoring & Incident Response (CC7.3)
- CloudWatch alarms for Lambda errors
- Slack notifications for critical issues
- Dashboard for system health monitoring
- Automated error handling and recovery

### 6. Data Retention (CC6.5)
- Email processing: Immediate deletion after handling
- Logs: 30-day retention in CloudWatch
- Conversation history: Configurable retention
- No PII stored beyond operational needs

## Compliance Checklist

- [x] No secrets in source code
- [x] Encryption at rest (AWS KMS)
- [x] Encryption in transit (TLS)
- [x] Audit logging enabled
- [x] Access controls implemented
- [x] Change tracking (Git + CHANGELOG)
- [ ] Regular security reviews
- [ ] Incident response plan documented
- [ ] Data retention policy enforced
- [ ] Penetration testing completed

## AWS Resources

### Lambda Functions
- Runtime: Python 3.12
- Encryption: Environment variables encrypted with KMS
- IAM Role: Least privilege access
- VPC: Optional for enhanced security

### Secrets Management
- Use AWS Secrets Manager for:
  - Microsoft Graph API credentials
  - Slack bot tokens
  - Atlassian API tokens
  - Azure AD client secrets

### Monitoring
- CloudWatch Logs: All Lambda invocations
- CloudWatch Metrics: Custom metrics for processing
- CloudWatch Alarms: Error rate thresholds

## Review Schedule
- Monthly: Security control review
- Quarterly: Compliance audit
- Annually: Full SOC2 assessment

## Last Updated
2025-10-13
