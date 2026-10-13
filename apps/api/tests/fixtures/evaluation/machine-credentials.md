# Aster Works Machine Credential Standard

Original fictional evaluation content, effective 15 September 2026.

## 1. Scope
This standard governs service API keys used by automated deployment clients. Human employee passwords follow the employee handbook. A rotation duration in one policy cannot be substituted for the other. The platform operations team owns service credentials. Secrets are issued through a managed credential broker; this document contains no real credentials.

## 2. Rotation and exceptions
Service API keys rotate every 30 days. Rotate a potentially exposed key immediately, revoke the old key after the replacement is confirmed, and record the event. An emergency extension requires platform operations approval and expires after seven calendar days. Human employee passwords are outside this policy's scope. Never use a shared employee identity as a deployment credential.

## 3. Deployment client
### 3.1 Configuration table
| Setting | Value | Meaning |
| --- | --- | --- |
| request_timeout_seconds | 20 | One request timeout |
| retry_attempts | 3 | Total attempts, including the initial request |
| connection_pool_size | 12 | Concurrent reusable connections |
| retry_backoff_seconds | 2 | Initial exponential backoff |

### 3.2 Retry rules
Retry only transient connection failures and server responses marked retryable. Do not retry permission rejection. The three-attempt limit includes the initial attempt, so there are at most two additional attempts. Apply exponential backoff with jitter and preserve the same operation identifier when a server supports idempotency.

## 4. Storage and rollout
Store issued keys in the managed broker and inject them into the client process at runtime. Never embed a key in a browser bundle or check it into source control. Before rotation, create the replacement, test the health endpoint, deploy the replacement and confirm normal traffic. Then revoke the old key. Deployment logs contain operation identifiers and safe status codes, not credential values.

## 5. Audit
Review service key inventories every Friday at 09:00 UTC. Each record has an owner, service name, issue date and expiry date. Unowned credentials are disabled after review. The next scheduled standard review is 15 September 2027. Audit archive retention is defined in the operations runbook, not by a deployment client's retry configuration.
