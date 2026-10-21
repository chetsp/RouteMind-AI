# Development and deployment

Run `docker compose up --build -d`, or the native commands in the README, from the repository root. Use the existing cloud checkout; do not create worktrees for routine cloud tasks.

The current cloud Docker daemon needed the platform's existing proxy hostname resolved into its build namespace and the machine's trusted CA supplied. The Dockerfile accepts an optional BuildKit secret `pip_ca_bundle`, e.g. `docker build --secret id=pip_ca_bundle,src=/path/to/trusted-ca-bundle -t routemind-ai-api .`. Forward proxy build arguments through your platform's supported route and use its DNS configuration. No credentials are written to the image and TLS verification remains enabled. Do not use insecure certificate flags or extract proxy credentials.

For production, replace demo database credentials with managed secrets, provide authenticated ingress with TLS, configure CORS, and implement tenant authorization before exposing shipment records. This project intentionally includes no public deployment automation or booking tools.

Persist SQL and `DATA_DIR` across restarts. The latter contains Chroma, LangGraph checkpoints and optional model weights. Processes do not survive cloud publication: start one Uvicorn worker after restore, check `/health`, and issue the known $2,100 request. Publication and validation in a new task are separate from current-instance testing.
