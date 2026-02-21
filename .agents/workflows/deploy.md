---
description: How to deploy the bot to the production server (FastVPS)
---

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

## Deploy Changes

4. Pull latest changes from GitHub:
```bash
cd /root/telegramMusic && git pull origin main
```

5. Install dependencies:
```bash
cd /root/telegramMusic && source venv/bin/activate && pip install -r requirements.txt
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
