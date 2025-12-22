# Tallyups Data Retention Policy

**Version:** 1.0
**Last Updated:** December 2025
**Owner:** Tallyups Development Team

## 1. Purpose

This policy defines how Tallyups collects, stores, retains, and deletes user data in compliance with applicable data privacy laws and best practices.

## 2. Scope

This policy applies to all data collected and processed by Tallyups, including:
- User account information
- Financial transaction data from connected banks (via Plaid)
- Receipt images and metadata
- Application logs and analytics

## 3. Data Categories and Retention Periods

### 3.1 Account Data
| Data Type | Retention Period | Justification |
|-----------|------------------|---------------|
| Email address | Account lifetime + 30 days | User identification |
| Password hash | Account lifetime | Authentication |
| 2FA secrets | Account lifetime | Security |
| Session tokens | 7 days | Active session management |

### 3.2 Financial Data (via Plaid)
| Data Type | Retention Period | Justification |
|-----------|------------------|---------------|
| Transaction history | 7 years | Tax/audit compliance |
| Account balances | 30 days (cached) | Performance |
| Bank account names | Account lifetime | Display purposes |
| Plaid access tokens | Until user disconnects | API access |

### 3.3 Receipt Data
| Data Type | Retention Period | Justification |
|-----------|------------------|---------------|
| Receipt images | 7 years | Tax documentation |
| OCR extracted text | 7 years | Search functionality |
| Receipt metadata | 7 years | Organization |
| Categorization | 7 years | Expense tracking |

### 3.4 System Logs
| Data Type | Retention Period | Justification |
|-----------|------------------|---------------|
| Application logs | 90 days | Debugging, monitoring |
| Access logs | 90 days | Security audit |
| Error logs | 90 days | Issue resolution |
| API request logs | 90 days | Rate limiting, security |

## 4. Data Collection Principles

### 4.1 Minimization
- Only collect data necessary for service functionality
- No collection of unnecessary sensitive information
- Regular review of data collection practices

### 4.2 Purpose Limitation
- Data used only for stated purposes:
  - Expense tracking and categorization
  - Financial reporting
  - Receipt management
- No secondary use without explicit consent

### 4.3 Accuracy
- Users can update their information at any time
- Regular validation of data integrity
- Automated cleanup of orphaned records

## 5. Data Storage

### 5.1 Primary Storage
- MySQL database (Railway-hosted)
- Encrypted at rest
- Regular automated backups

### 5.2 Object Storage
- Cloudflare R2 for receipt images
- AES-256 encryption
- Redundant storage

### 5.3 Geographic Location
- All data stored in US data centers
- No international data transfer

## 6. User Rights

### 6.1 Right to Access
Users can request a copy of all their personal data:
- Submit request via settings page
- Data provided within 30 days
- Export format: JSON/CSV

### 6.2 Right to Rectification
Users can correct inaccurate data:
- Edit profile information
- Update transaction categorizations
- Modify receipt metadata

### 6.3 Right to Deletion
Users can request account and data deletion:
- Available via settings page
- Processing within 30 days
- Certain data retained for legal compliance (see Section 7)

### 6.4 Right to Data Portability
Users can export their data:
- Transaction history (CSV/Excel)
- Receipt images (ZIP)
- Account information (JSON)

## 7. Legal Holds and Exceptions

### 7.1 Tax Compliance
Financial records may be retained beyond user deletion request for:
- IRS requirements (7 years for tax records)
- State tax requirements (varies by state)
- Active audit periods

### 7.2 Legal Proceedings
Data may be retained if:
- Subject to ongoing litigation
- Required by law enforcement request
- Needed for legal defense

### 7.3 Fraud Prevention
Certain data retained to prevent:
- Account abuse
- Fraudulent activity
- Terms of service violations

## 8. Data Deletion Procedures

### 8.1 User-Initiated Deletion
1. User requests deletion via settings
2. Confirmation email sent
3. 14-day grace period (recoverable)
4. Permanent deletion after grace period
5. Deletion confirmation sent

### 8.2 Automated Deletion
- Expired sessions: Immediate
- Temporary files: 24 hours
- Cached data: 30 days
- Orphaned records: Weekly cleanup

### 8.3 Deletion Verification
- Deletion logged for audit trail
- Quarterly verification of deletion processes
- Backup expiration enforced

## 9. Third-Party Data Sharing

### 9.1 Service Providers
Data shared only with essential service providers:

| Provider | Data Shared | Purpose |
|----------|-------------|---------|
| Plaid | Bank credentials | Bank connectivity |
| Cloudflare | Receipt images | Storage |
| Railway | All app data | Hosting |
| Google | OAuth tokens | Authentication |

### 9.2 No Data Sale
- **We do not sell user data**
- No sharing for marketing purposes
- No third-party analytics that track users

## 10. Data Breach Response

In case of a data breach:
1. Immediate containment
2. Assessment of affected data
3. User notification within 72 hours
4. Regulatory notification if required
5. Remediation and prevention

See [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for details.

## 11. Policy Updates

- Policy reviewed quarterly
- Users notified of material changes
- 30-day notice before changes take effect

## 12. Contact

For data-related inquiries:
- Email: privacy@tallyups.com
- Response within 7 business days

---

*This policy complies with applicable data protection regulations and is subject to periodic review.*
