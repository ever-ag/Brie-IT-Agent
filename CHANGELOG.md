# Changelog

All notable changes to the Brie IT Agent project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed
- Removed false "cannot view images" messaging - bot now correctly processes images with Claude Vision without claiming it can't see them
- Hardware detection now catches tickets like "Rachel Ranslow needs to be setup on an Ever.ag laptop" (previously missed)

### Changed
- Expanded hardware request detection keywords to catch more variations including "needs a laptop", "setup on a computer", "laptop for [person]", etc.

### Fixed
- Hardware detection now catches tickets like "Rachel Ranslow needs to be setup on an Ever.ag laptop" (previously missed)

### Added
- Initial repository setup
- Core Lambda functions for email processing
- Slack bot integrations
- Step Functions workflows
- Documentation and dashboards
- Q CLI configuration with AWSCorp profile
- SOC2 compliance requirements

### Security
- Removed all hardcoded secrets from codebase
- Implemented placeholder tokens for secure credential management
- Added .gitignore for secret protection

## [1.0.0] - 2025-10-13

### Added
- Brie IT Agent automated helpdesk system
- Claude AI integration for intelligent responses
- Microsoft Graph API integration
- 15 detection steps covering 95-98% of IT support scenarios
- Image analysis with Claude Vision
- AWS infrastructure components
