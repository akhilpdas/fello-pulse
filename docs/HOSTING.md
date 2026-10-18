# Putting the demo in front of a reviewer

Nothing here is deployed yet; these are the steps, cheapest first. Both use the container stack (`docker compose`), which serves the UI and the API on one address, so one link is all a reviewer needs.

**Before you share any link:** every demo user shares one password. Choose your own (at least 12 characters) and give it to the reviewer in the message, never in the repository. Demo mode is on by default, so no email reaches a real person even if the reviewer clicks *Approve & send*.

## A. From your Mac, free, ready in 10 minutes (the link works only while the Mac is awake and connected)

```bash
brew install cloudflared                       # once
export PULSE_DEMO_PASSWORD='your chosen passphrase'
docker compose up -d --build                   # needs Docker (Colima is installed): `colima start` first
docker compose run --rm api python3 -m pulse.cli bootstrap-demo     # ~5 min: builds the estate, trains, scores
docker compose run --rm api python3 -m pulse.cli backfill --weeks 8 # ~12 min: earlier weeks for the Week picker
cloudflared tunnel --url http://localhost:5173 # prints https://<random>.trycloudflare.com  -> send that link
```

The link changes every time the tunnel restarts, and it dies when you close the terminal or the lid. Fine for a reviewer who looks within a day or two; send a screen recording as well.

## B. A small cloud server (a link that stays up) — about $25–30 a month, or covered by new-account credits

- AWS: a new account gets Free Plan credits ($100, up to $100 more for onboarding tasks). The plan ends after six months or when the credits run out, and it needs a card. Pick a Graviton instance (`t4g.medium`, 4 GB, Amazon Linux or Ubuntu arm64) because the images are verified on arm64.
- On the server: install Docker, `git clone https://github.com/akhilpdas/fello-pulse`, then run the same four commands as above (without the tunnel).
- Put a TLS front in front of port 5173 (Caddy is one line: `caddy reverse-proxy --from demo.example.com --to localhost:5173`) and set `PULSE_COOKIE_SECURE=true`. Open only ports 80/443 in the security group.
- Stop or terminate the instance when the review is over.

I have not deployed either option, so treat the commands as unverified until you have run them once.

## What to send

1. The link and the password (message body only), the workspace names and the operator email from `docs/DEMO_GUIDE.md`.
2. `docs/Pulse_Test_Walkthrough.pdf` (35 pages, with screenshots) and the repo link.
3. The recorded walkthrough (script: `docs/LOOM_SCRIPT.md`).
