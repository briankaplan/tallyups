# Tallyups Security Policy

**Version:** 1.0
**Last Updated:** December 2025
**Owner:** Tallyups Development Team

## 1. Overview

This document outlines the security practices and controls implemented in Tallyups, a personal finance and expense tracking application. Our security program is designed to protect user data, ensure system integrity, and maintain compliance with industry standards.

## 2. Hosting and Infrastructure

### 2.1 Cloud Hosting
- **Platform:** Railway (Platform-as-a-Service)
- **Infrastructure Provider:** Google Cloud Platform (GCP) / AWS
- **Regions:** US-based data centers
- **Benefits:**
  - SOC 2 Type II compliant infrastructure
  - Automatic security patching
  - DDoS protection
  - Network isolation between services

### 2.2 Architecture
- Containerized application deployment
- Isolated production and development environments
- No direct access to production systems
- All deployments through CI/CD pipeline (GitHub Actions)

## 3. Authentication and Access Control

### 3.1 User Authentication
- Password-based authentication with bcrypt hashing (cost factor 12)
- Session-based authentication with secure, HTTP-only cookies
- Session timeout after 7 days of inactivity
- Timing-safe password comparison to prevent timing attacks

### 3.2 Two-Factor Authentication (2FA)
- TOTP-based 2FA (RFC 6238) compatible with:
  - Google Authenticator
  - Authy
  - Microsoft Authenticator
  - 1Password
- Backup codes for account recovery
- 2FA required for sensitive operations

### 3.3 Biometric Authentication
- WebAuthn/FIDO2 support for Face ID and Touch ID
- Platform authenticator verification
- Credential binding to device

### 3.4 API Authentication
- Admin API keys for service-to-service communication
- API keys stored as environment variables, never in code
- Rate limiting on all API endpoints

### 3.5 Access Control Matrix
| Role | Dashboard | Settings | Bank Connection | Admin |
|------|-----------|----------|-----------------|-------|
| User | Yes | Yes | Yes | No |
| Admin | Yes | Yes | Yes | Yes |

## 4. Data Protection

### 4.1 Encryption in Transit
- TLS 1.2+ for all connections
- HTTPS enforced on all endpoints
- Automatic certificate provisioning via Railway/Let's Encrypt
- HSTS headers enabled

### 4.2 Encryption at Rest
- Database encryption enabled (Railway MySQL)
- Object storage encryption (Cloudflare R2 - AES-256)
- No plaintext storage of sensitive credentials

### 4.3 Sensitive Data Handling
- OAuth tokens encrypted before storage
- Plaid access tokens stored securely in database
- No storage of full credit card numbers
- PII minimization practices

## 5. Network Security

### 5.1 Network Segmentation
- Production database not publicly accessible
- Internal service communication via private networks
- API endpoints exposed through load balancer
- Firewall rules limiting ingress/egress

### 5.2 DDoS Protection
- Cloudflare protection for public endpoints
- Rate limiting via Flask-Limiter
- Request size limits

## 6. Vulnerability Management

### 6.1 Dependency Scanning
- Regular npm/pip audit for dependencies
- Automated security updates via Dependabot
- Vulnerability tracking and patching

### 6.2 Code Security
- Code review required for all changes
- No secrets in source code
- Git pre-commit hooks for secret detection

### 6.3 Security Headers
- Content Security Policy (CSP)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- X-XSS-Protection: 1; mode=block

## 7. Logging and Monitoring

### 7.1 Audit Logging
- All API requests logged with:
  - Timestamp
  - Request ID
  - User identifier
  - Action performed
  - Response status
- Logs retained for 90 days

### 7.2 Monitoring
- Real-time error tracking
- Performance monitoring
- Alert rules for:
  - High error rates
  - Database connection issues
  - Authentication failures

### 7.3 Alerting
- Automated alerts for security events
- Incident escalation procedures
- On-call notification system

## 8. Change Management

### 8.1 Development Workflow
1. Changes made in feature branches
2. Code review required
3. Automated tests must pass
4. Merge to main triggers deployment
5. Health checks verify deployment success

### 8.2 Production Deployments
- Blue-green deployment strategy
- Automatic rollback on failure
- Database migrations versioned and reversible

## 9. Third-Party Security

### 9.1 Vendor Assessment
All third-party services evaluated for:
- SOC 2 compliance
- Security certifications
- Data handling practices
- Incident response capabilities

### 9.2 Approved Vendors
| Vendor | Purpose | Compliance |
|--------|---------|------------|
| Railway | Hosting | SOC 2 |
| Cloudflare | CDN/R2 Storage | SOC 2, ISO 27001 |
| Plaid | Bank Connectivity | SOC 2, PCI DSS |
| Google Cloud | APIs | SOC 2, ISO 27001 |

## 10. Incident Response

See [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for detailed procedures.

### 10.1 Severity Levels
- **Critical:** Data breach, system compromise
- **High:** Service outage, authentication failure
- **Medium:** Performance degradation
- **Low:** Minor issues

### 10.2 Response Timeline
| Severity | Response Time | Resolution Target |
|----------|---------------|-------------------|
| Critical | 15 minutes | 4 hours |
| High | 1 hour | 8 hours |
| Medium | 4 hours | 24 hours |
| Low | 24 hours | 72 hours |

## 11. Data Privacy

### 11.1 Data Collection
- Only data necessary for service operation
- No sale of user data
- No sharing with third parties except service providers

### 11.2 User Rights
- Right to access personal data
- Right to delete account and data
- Right to export data

See [DATA_RETENTION_POLICY.md](DATA_RETENTION_POLICY.md) for details.

## 12. Compliance

### 12.1 Standards
- OWASP Top 10 awareness
- Security best practices
- Regular security assessments

### 12.2 Certifications
- Working toward SOC 2 Type II
- Plaid production access approved

## 13. Contact

For security concerns or to report vulnerabilities:
- Email: security@tallyups.com
- Response within 24 hours for all security reports

---

*This policy is reviewed and updated quarterly.*
