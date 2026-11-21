# Lyftr

React + TypeScript chat frontend with a FastAPI backend, SQLite session history, LiteLLM disk caching, and deterministic Groq key failover.

## Live URLs

| Service | URL | State |
| --- | --- | --- |
| Frontend | https://lyftr.nishantraj.me | Public chat, follow-up, fresh-session cache and exact-domain CORS verified |
| Backend | https://16.179.206.95.sslip.io | AWS EC2 HTTPS, public API smoke and restart persistence verified |
| Repository | https://github.com/nishantnsut27/lyftr-assignment | Public |
| Demo | Add the narrated 2-3 minute recording URL | Pending |

Local frontend: http://localhost:3000. Local backend: http://localhost:8000.

The frontend is hosted on Vercel with the custom domain above. The backend runs on AWS EC2 with persistent SQLite history and LiteLLM disk cache under `/data`.

## Run locally: with Docker and without

### Choose the environment file

All files live at the repository root. `.env.example` contains public placeholders; private environment files stay ignored.

| File | Use |
| --- | --- |
| `.env` | Local Docker Compose, local backend, and local Vite configuration; start from `.env.example`. |
| `.env.vercel` | Prepared public frontend API URL setting; import into Vercel. |
| `.env.aws` | Prepared private AWS EC2 backend settings; copy to the VM over SSH. |

Private environment files are ignored and are never uploaded to GitHub. New clones receive `.env.example` with placeholders. Configure the backend on EC2 and set `VITE_API_BASE_URL` in Vercel Production; Vercel embeds that public URL during its build.

### Docker

Install Docker with Compose and GNU Make. Copy `.env.example` to `.env`, replace `LLM_API_KEYS` with at least two distinct Groq keys in the intended fallback order, and keep these local values:

```dotenv
FRONTEND_PORT=3000
PORT=8000
VITE_API_BASE_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:3000
```

```sh
make up
make down
```

`make up` builds both images and waits for healthy containers. The frontend binds to localhost:3000 and the backend to localhost:8000. Vite development/preview and container Nginx also use port 3000. If another project owns that port, stop or move that project before the assignment check.

`make down` preserves the `lyftr_data` named volume. Compose always stores SQLite at `/data/app.db` and cache at `/data/llm-cache`; local non-Docker paths do not override these container paths. No data folder, database or cache contents need to be uploaded to GitHub: Compose creates the volume and the backend initializes its files on startup.

On Windows without GNU Make, the equivalent commands are:

```sh
docker compose --project-name lyftr up --build --detach --wait --wait-timeout 180
docker compose --project-name lyftr down --timeout 30
```

### Without Docker

Use Python 3.12, uv, and Node.js 22.12 or later. Create the root `.env` using `.env.example`, retain its relative local database/cache paths, and configure the real backend keys.

From the repository root, start the backend:

```sh
uv sync --project backend --locked --python 3.12
uv run --project backend --locked uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

In a second terminal:

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

### Deploy backend on AWS EC2

The backend is deployed at https://16.179.206.95.sslip.io on Ubuntu 24.04 EC2 instance `i-0cad29b75bef82484` in `ap-southeast-2`. Commit `1015706` runs from `/home/ubuntu/lyftr-assignment` with Docker Engine 29.10.0 and Compose v5.8.0. Caddy serves a verified Let's Encrypt certificate and redirects HTTP to HTTPS. The backend runs as UID 10001 with one worker; port 8000 stays inside Docker. SQLite and LiteLLM cache use `lyftr_aws_data` on the 20 GB EBS root disk. Three keys are configured in the ignored `.env.aws`, mode 600, with explicit frontend origins and failure simulation enabled.

Public health/chat/history/cache, one/two-key failover, exact wildcard 503, failure atomicity, CORS and actual backend restart persistence passed on 2026-11-21. The smoke measured 457 ms live and 2 ms cached, preserving 117 input and 88 output tokens. Evidence is in `.cache/aws/`. AWS account credits, billing eligibility and provider account spend settings have not been inspected.

The frontend at https://lyftr.nishantraj.me is connected to the AWS API. Both the custom domain and https://lyftr-assignment.vercel.app are allowed explicitly by the backend; an unrelated origin is rejected. Public browser acceptance passed all 38 responsive/accessibility states, keyboard/focus/scroll checks, live first-message/follow-up and fresh-session cache journeys on 2026-11-21. The CORS update recreated only the backend using the same image and persistent volume; existing SQLite history and cached replies/token usage survived. The latest public smoke measured 202 ms live and 2 ms cached, with identical 114 input and 82 output tokens. Source/build and deployed source/image/log credential scans passed.

The hostname uses the instance's current public IP. An EC2 stop/start can change that address; update the hostname and frontend URL if it changes. Container restarts retain the existing EBS-backed volume. Retain the VM and its disk to keep history/cache; termination and disk deletion were not tested.

The following steps reproduce the deployed backend:

1. Create a new [AWS Free Tier account](https://aws.amazon.com/free/) and select **Free plan**. Eligible new customers receive $100 initial credits and can earn up to $100 more. The plan ends after six months or credit exhaustion, whichever happens first. It is temporary hosting. AWS currently says most new customers do not need a payment method at signup, though verification may request one. Confirm the actual plan and credit balance in the account. [AWS Free Tier terms](https://aws.amazon.com/free/free-tier-faqs/) apply.
2. In the AWS Console choose a nearby available region, such as Mumbai (`ap-south-1`), then **EC2 > Instances > Launch instances**. Name it `lyftr-backend`, use the official Ubuntu 24.04 LTS x86_64 AMI, and choose `t3.small` (2 GB RAM) if marked Free Tier eligible for the account. This offers more memory for LiteLLM than a micro instance and consumes credits faster. Use a 20 GB encrypted `gp3` root EBS disk. Compute, storage and public IPv4 usage consume the available credits; eligibility does not make an EC2 VM permanently free. [EC2 Free Tier rules](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html) distinguish account plans.
3. Create/download an RSA `.pem` key pair named `lyftr-aws`, and keep the private key local. Use the default VPC with a public subnet and enable automatic public IPv4 assignment. In the security group allow SSH (22) from **My IP**, and HTTP (80) / HTTPS (443) from the internet. Review the launch summary against the account's Free plan. Once running, connect to its public IP as `ubuntu`. Port 8000 stays internal to the Docker network.
4. Install [Docker Engine and the Compose plugin for Ubuntu](https://docs.docker.com/engine/install/ubuntu/) and Git, then clone the public repository on the VM.
5. Copy the private `.env.aws` to the repository root over SSH/SCP; it contains the existing backend keys. Keep permissions at `chmod 600 .env.aws`. Set `BACKEND_HOSTNAME` to a DNS hostname resolving to the VM, for example `YOUR_PUBLIC_IP.sslip.io`. Set `ALLOWED_ORIGINS=https://lyftr.nishantraj.me,https://lyftr-assignment.vercel.app` to allow both exact frontend origins.
6. From the VM repository root, start the backend and HTTPS proxy:

```sh
sudo docker compose --env-file .env.aws -f docker-compose.aws.yml up --build -d --wait --wait-timeout 300
```

Caddy automatically obtains HTTPS certificates once the hostname resolves correctly and ports 80/443 are reachable. [Automatic HTTPS requirements](https://caddyserver.com/docs/automatic-https) apply. The [sslip.io DNS service](https://nip.io/) derives the IP from the hostname; an owned domain pointing to the VM also works. The public hostname and certificate issuance must be verified on the actual VM.

SQLite and LiteLLM cache use the persistent `lyftr_aws_data` Docker volume mounted at `/data` on the EBS disk. Caddy certificate state has separate persistent volumes. Stopping/recreating containers keeps those volumes; the VM and its EBS disk must also be retained. There is one backend worker, and public traffic reaches it through Caddy.

7. Confirm `https://YOUR_BACKEND_HOSTNAME/health` returns 200. Set Vercel's Production `VITE_API_BASE_URL` to `https://YOUR_BACKEND_HOSTNAME`, update the private `.env.vercel`, and redeploy the frontend. Do not use an HTTP IP URL from the HTTPS frontend.
8. Run the public smoke from your local machine with the AWS backend URL and `--origin https://lyftr.nishantraj.me`. Restart the backend container on the VM, then repeat with the same checkpoint and `--verify-restart`. Record the actual URL only after health/chat/history/cache/failover/CORS and persistence pass.

AWS Compose, deployed runtime, certificate issuance, public HTTP/HTTPS connectivity, API behavior and backend restart persistence are verified. The account plan/credit balance and security-group source rules were not inspected in the console.

### Vercel frontend and custom-domain CORS

| Vercel setting | Value |
| --- | --- |
| Framework preset | Vite |
| Root directory | `frontend` |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Node.js | 22.x |
| Production variable | `VITE_API_BASE_URL=https://16.179.206.95.sslip.io` |
| Custom domain | `lyftr.nishantraj.me` |

`frontend/vercel.json` records the build settings. Vercel serves the built static frontend over HTTPS. Configure only the public API URL in the frontend; provider keys belong exclusively on the backend.

Adding a custom domain in Vercel also requires updating the backend's private `.env.aws`:

```dotenv
ALLOWED_ORIGINS=https://lyftr.nishantraj.me,https://lyftr-assignment.vercel.app
```

After changing that environment file, run this from the EC2 repository root. Recreating the backend reloads its settings and preserves the named history/cache volume:

```sh
sudo docker compose --env-file .env.aws -f docker-compose.aws.yml up -d --no-build --no-deps --wait --wait-timeout 60 backend
```

Each permitted origin must be explicit. Preview domains require their own entries. DNS changes and Git pushes do not update private runtime environment files.

Vite embeds `VITE_API_BASE_URL` during the build. Changing it in Vercel requires a new deployment. The selected variable must apply to the Production environment. See [Vercel environment variables](https://vercel.com/docs/environment-variables) and [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite).

Set provider spend limits before exposing the public backend. The assignment does not require application authentication, and session IDs are conversation identifiers rather than authorization tokens.

## Design decisions: key fallback, caching, SQLite session storage

HTTP validation, configuration, SQLite persistence, session coordination, and LiteLLM inference live in separate backend modules. Tests inject inference; production always calls LiteLLM.

Keys use one configured model, defaulting to `groq/openai/gpt-oss-20b`. Eligible rate-limit, quota, and provider 5xx failures advance through the configured keys in order. Hidden provider retries are disabled. Public errors contain safe JSON details without provider exceptions or credentials.

LiteLLM's built-in disk cache identifies completions by the model and full system/history/new-user message list. Session IDs, credentials, and failure headers do not enter cache identity. Hits retain the original reply and usage, with null `key_id`, zero fallbacks, and measured request latency. Enabled failure simulation bypasses cache reads.

SQLite stores each session's effective system prompt separately from user/assistant history. A successful prompt and message pair commit together; failed inference does not mutate history. Each session's full read/infer/write operation is serialized. WAL and short transactions allow unrelated sessions to progress independently. One backend worker is required because these locks are in-process.

The frontend sends only the new message and optional prompt. It starts a fresh session on page load and displays source, model, latency, and per-inference input/output usage for every reply.

## Verification: how to see failover, cache hits and per-message token usage

### Local checks

```sh
uv run --project backend --locked pytest
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format --check backend
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run test:e2e
uv run --project backend --locked python scripts/check_secrets.py
```

Browser acceptance defaults to http://localhost:3000 and needs the running real backend. The complete backend smoke verifies health, context, history isolation/order, exact errors, cache identity/usage, one/two-key failover, wildcard failure, recovery, and frontend CORS:

```sh
uv run --project backend --locked python scripts/smoke_backend.py --url http://localhost:8000 --origin http://localhost:3000
```

### Public verification and restart

The deployed AWS backend and custom-domain frontend origin are used below. The smoke uses the public API and does not need to read or print keys. It makes real provider requests and saves a local checkpoint.

```sh
uv run --project backend --locked python scripts/smoke_backend.py --url https://16.179.206.95.sslip.io --origin https://lyftr.nishantraj.me --checkpoint .cache/aws/public-smoke.json
```

Restart the backend container on EC2 with its existing volume, then:

```sh
uv run --project backend --locked python scripts/smoke_backend.py --url https://16.179.206.95.sslip.io --origin https://lyftr.nishantraj.me --checkpoint .cache/aws/public-smoke.json --verify-restart
```

Open the production frontend, send a first message, ask a follow-up, then reload and repeat the identical first message. Expect a new session with the identical cached reply and usage. A different first prompt should infer live. Usage describes that request's complete prompt and reply, not accumulated session usage.

For the demo, call `POST /chat` with these headers while `ENABLE_FAILURE_SIMULATION=true`:

| Header | Expected result |
| --- | --- |
| `X-Simulate-Failure: key_1=429` | Real 200 reply from `key_2` |
| `X-Simulate-Failure: key_1=429,key_2=500` | Real 200 reply from `key_3` |
| `X-Simulate-Failure: *=429` | 503 `{"detail":"all providers unavailable"}`; unchanged history |

Only `GET /health`, `POST /chat`, and `GET /sessions/{session_id}/messages` are public application routes. Automatic API documentation is disabled.

If the UI loads but chat fails, check the backend `/health`, the frontend's built API base URL, and the exact CORS origin first. Public smoke, exact-domain CORS, connected browser acceptance and retained history/cache checks passed on 2026-11-21.

## Setup Used: your editor and AI tools

OpenAI Codex assisted implementation and verification on Windows using PowerShell, uv/Python 3.12, npm/Node.js, Docker Desktop, and Chromium/Playwright. A separate editor name has not been recorded; add it if used. No editor or hosting-dashboard verification is claimed without evidence.

## Bonus features (if any): what you added beyond the requirements and why

- Optional session system prompt, persisted only after successful inference.
- Accessible keyboard/focus behavior, responsive layout, and separate retry/edit controls for failed messages.
- Deterministic three-key failover and disk-cache persistence across restarts.
