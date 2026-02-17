# Threat Model

## Assets
1. **Documents**: Source files uploaded to S3 (potentially sensitive)
2. **Embeddings**: Vector representations of document content
3. **API keys**: OpenAI API key, DB credentials
4. **Query data**: User questions (may contain sensitive context)

## Threats & Mitigations

### T1: Credential exposure
- **Risk**: API keys or DB passwords leaked in code/logs
- **Mitigation**:
  - Secrets in SSM/Secrets Manager (never in code)
  - `.env` in `.gitignore`
  - Aurora auto-managed passwords
  - Structured logging excludes secret fields

### T2: Unauthorized API access
- **Risk**: Public API allows unrestricted access
- **Mitigation**:
  - API Gateway can be configured with API keys or IAM auth
  - Input validation (2000 char limit on questions)
  - Rate limiting via API Gateway throttling
  - VPC-based network isolation for database

### T3: Data exfiltration via queries
- **Risk**: Crafted queries extract sensitive document content
- **Mitigation**:
  - Collection-based access scoping
  - Configurable `top_k` limits
  - Optional: redact known sensitive patterns (AWS keys, SSNs) at ingest time

### T4: Injection attacks
- **Risk**: Prompt injection via user questions
- **Mitigation**:
  - Input length limits
  - Structured prompt template (context and question separated)
  - Retrieval-only mode available (no LLM = no prompt injection)

### T5: Network exposure
- **Risk**: Database accessible from internet
- **Mitigation**:
  - Aurora in private subnets (VPC)
  - Security group restricts to Lambda IPs
  - No public endpoint on Aurora

## Security Checklist
- [x] No secrets in repo (`.gitignore`, Secrets Manager)
- [x] IAM least privilege (separate query/ingest roles)
- [x] S3 encryption (KMS) + public access block
- [x] Input validation + limits
- [x] Structured logging (no secret leakage)
- [ ] API authentication (add for production)
- [ ] WAF rules (add for production)
- [ ] VPC flow logs (add for compliance)
