# AWS Cost Notes

## Design Decisions

This is a portfolio, not a production system. Resources are sized for demonstration, not scale.

## Monthly Cost Estimate

| Resource | Config | Est. Monthly |
|----------|--------|-------------|
| RDS PostgreSQL | db.t4g.micro, 20GB gp3, single-AZ | ~$13 |
| S3 (web + data) | < 5GB, low traffic | ~$0.50 |
| CloudFront | < 10GB transfer | ~$1 |
| Lambda | < 1M requests (free tier) | $0 |
| API Gateway | < 1M requests (free tier) | $0 |
| **Total** | | **~$15/month** |

## What Was Intentionally Avoided

| Resource | Why Avoided |
|----------|-------------|
| Multi-AZ RDS | No redundancy needed for portfolio |
| NAT Gateway | ~$32/month for no benefit here |
| ALB/NLB | Unnecessary for static + Lambda architecture |
| Large EC2 | No compute workloads need always-on instances |
| ECS/Fargate (GeoServer) | Would add ~$15-30/month; Docker local is sufficient |
| ElastiCache | Query patterns don't require caching |
| RDS Proxy | Not needed at this connection volume |

## Shutdown Instructions

To destroy all portfolio resources and stop costs:

```bash
cd infrastructure/terraform
terraform destroy -var="db_password=YOUR_PASSWORD"
```

The destroy only targets resources prefixed with `egehan-geo-`.

## Free Tier Notes

- Lambda: 1M requests/month free
- API Gateway: 1M HTTP API calls/month free (first 12 months)
- S3: 5GB storage free (first 12 months)
- CloudFront: 1TB transfer free (first 12 months)

After free tier expires, add approximately $3-5/month.
