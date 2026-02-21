---
description: How to deploy the bot to the production server (FastVPS)
---

## Important Notes

- **Auto-deploy**: Pushing to `main` triggers GitHub Actions which automatically pulls code, installs deps, and **restarts the bot** via `systemctl restart telegram-suno-bot`. No manual restart needed after push.
- **`.env` is preserved**: The deploy pipeline only creates `.env` on first deploy. On subsequent deploys it updates only secrets (BOT_TOKEN, API keys, ADMIN_TOKEN, DATABASE_URL) via `sed`, preserving runtime settings (SUNO_MODEL, FREE_CREDITS_ON_SIGNUP, limits etc.) changed through the admin panel.
- **Never suggest restarting the server** — it happens automatically on deploy.
- The app directory on the server is `/opt/telegram-suno-bot`.

## Server Access

- **Provider**: FastVPS
- **IP**: 5.45.112.38
- **User**: root
- **Password**: N6fRfGvE2s67s7Un
- **Port**: 22 (SSH)

## Connect to Server

// turbo
1. SSH into the server:
```bash
ssh root@5.45.112.38
```

## Check Bot Status

// turbo
2. Check if the bot service is running:
```bash
systemctl status telegram-suno-bot
```

// turbo
3. View recent logs:
```bash
journalctl -u telegram-suno-bot -n 100 --no-pager
```

## Manual Deploy (if needed)

4. Pull latest changes from GitHub:
```bash
cd /opt/telegram-suno-bot && git pull origin main
```

5. Install dependencies:
```bash
cd /opt/telegram-suno-bot && source venv/bin/activate && pip install -r requirements.txt
```

6. Ask the user to restart the bot service (never restart automatically):
```
systemctl restart telegram-suno-bot
```

## View Logs

// turbo
7. Tail live logs:
```bash
journalctl -u telegram-suno-bot -f
```
