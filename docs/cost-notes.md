# Cost Notes

## Aurora Serverless v2

| Setting | Dev | Prod |
|---------|-----|------|
| Min ACU | 0.5 | 2 |
| Max ACU | 2 | 16 |
| Storage | Pay per GB | Pay per GB |

**Estimated dev cost**: ~$45/month (0.5 ACU idle + minimal storage)

### Cost optimization
- Set `min_acu = 0.5` for dev (lowest possible)
- Aurora scales to near-zero when idle
- Consider pausing the cluster during non-work hours

## OpenAI API

| Model | Cost | Dimensions |
|-------|------|-----------|
| text-embedding-3-small | $0.02 / 1M tokens | 1536 |
| gpt-4o-mini | $0.15 / 1M input, $0.60 / 1M output | — |

### Cost optimization
- SHA256 caching avoids re-embedding unchanged documents
- Batch embedding calls (up to 2048 texts per request)
- Use retrieval-only mode (no LLM) for development/testing
- Limit `max_tokens` in LLM responses

## Lambda

- Free tier: 1M requests + 400K GB-seconds/month
- Query Lambda: 512 MB × 30s max = minimal cost
- Ingest Lambda: 1024 MB × 300s max = watch for large ingestion jobs

## S3

- Standard storage: ~$0.023/GB/month
- Versioning enabled (costs 2x for updates)
- For dev, total cost negligible

## Total Estimated Dev Cost

| Component | Monthly Estimate |
|-----------|-----------------|
| Aurora Serverless v2 | ~$45 |
| OpenAI (moderate use) | ~$5 |
| Lambda | Free tier |
| S3 | < $1 |
| API Gateway | < $1 |
| **Total** | **~$52/month** |
