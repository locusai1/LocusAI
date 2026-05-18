---
name: Permanent Cloudflared Tunnel
description: Need to replace the temporary cloudflared tunnel with a permanent named tunnel or production server
type: project
---

Retell webhooks currently rely on a temporary cloudflared tunnel (`cloudflared tunnel --url http://localhost:5050`) which generates a new random URL on every restart. This means after every server restart, the Retell agent's webhook_url needs to be manually updated.

**Why:** Temporary tunnels are not reliable for production — the URL changes on restart, breaking real-time call logging.

**How to apply:** When the user is ready to make voice production-ready, set up one of:
1. **Named cloudflared tunnel** (free): `cloudflared tunnel create locusai` → permanent subdomain on trycloudflare.com
2. **Production server** (VPS/cloud): Deploy Flask to a real server with a fixed domain, configure HTTPS, point Retell webhook to it permanently

**Current state:** Temporary tunnel working at session start, Retell agent `agent_7fe6433627a68c931f05b7ae84` webhook_url updated manually each time.
