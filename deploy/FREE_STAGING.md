# Free staging deployment

This configuration uses two **Render Free** services (a static React frontend
and a FastAPI API), plus a **Neon Free** PostgreSQL project. It is for
evaluation and test data only, not production.

## Limits to expect

- Render Free web services sleep after 15 minutes without inbound traffic and
  can take about a minute to start again. The free workspace allowance is
  limited to 750 instance-hours per calendar month. [Render Free plan details](https://render.com/docs/free).
- Neon Free is $0/month and does not require a credit card. It includes 1 GB
  storage per project and 100 compute-unit hours per project; compute scales
  to zero after five minutes of inactivity. [Neon plan details](https://neon.com/docs/introduction/plans).
- Neither service provides a production availability or performance guarantee.
  Do not store real business data or rely on this staging environment for
  backups or recovery.

## Setup

1. Create a Neon project on its Free plan in the Frankfurt region. Keep the
   default database branch empty for staging. Neon project regions are fixed
   at creation; Frankfurt is `aws-eu-central-1` ([region list](https://neon.com/docs/introduction/regions)).
2. Copy the **pooled** connection string from Neon. Keep it private; do not
   paste it into chat, commit it, or save it in the repository.
3. In Render, create a Blueprint from this repository and select the `main`
   branch. Review the Blueprint before applying it; it creates two Free
   services and no Render database.
4. When Render prompts for `DATABASE_URL`, enter the Neon pooled connection
   string. Render generates `SECRET_KEY` automatically. The API and frontend
   URLs are configured in `render.yaml`; if Render reports that either name is
   unavailable, rename both services there and update the matching API/CORS
   URLs. Do not add billing or upgrade either service for this staging setup.
5. Wait for the API health check and frontend deploy to pass, then open
   `https://ai-erp-system-staging-web.onrender.com`. The first backend startup
   applies Alembic migrations to the new, empty staging database. Create the
   initial admin account in the app.
6. Test only with synthetic data. If the free quotas are reached or the
   provider requests an upgrade/payment method, stop and review before
   proceeding; do not upgrade automatically.

To reset this disposable staging database, delete its Neon project or branch
from the Neon dashboard. Never point this deployment at a production database.
