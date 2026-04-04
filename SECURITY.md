# Security Policy

## Supported Versions

Security fixes are currently provided for the active default branch only.

| Version | Supported |
| --- | --- |
| `main` | :white_check_mark: |
| Other branches/tags | :x: |

## Reporting a Vulnerability

Use **GitHub Private Vulnerability Reporting** in this repository:

1. Open the repository on GitHub.
2. Go to `Security` -> `Advisories`.
3. Click `Report a vulnerability`.
4. Provide reproduction steps, impact, and suspected affected components.

Do not open public issues for suspected vulnerabilities.

## Response SLA

- Initial acknowledgment: within **48 hours**.
- Triage and severity classification: within **5 business days**.
- First remediation plan (or mitigation guidance): within **7 business days** after triage.
- Ongoing status updates: at least every **7 calendar days** until closure.

## Severity Targets

- Critical: mitigation or fix target within **7 calendar days**.
- High: mitigation or fix target within **14 calendar days**.
- Medium/Low: scheduled in the nearest planned release train.

## Scope

Examples of in-scope reports:

- authentication and authorization bypass
- cross-tenant data access or leakage
- secret exposure
- SSRF/path traversal/injection in ingestion and retrieval flows
- privilege escalation in admin-only workflows

Out of scope:

- requests for broad best-practice changes without a concrete vulnerability
- missing security headers on non-production local environments
- reports that require unrealistic attacker assumptions with no impact path

## Coordinated Disclosure

Please keep vulnerability details private until a fix is released and maintainers confirm disclosure timing.
