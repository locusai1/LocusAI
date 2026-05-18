# LocusAI Memory

## Project State
- Business: Style Cuts, ID 1 (only business)
- Voice agent: Retell native LLM, agent_7fe6433627a68c931f05b7ae84, LLM llm_b41019c52636d5321f084e5bdbbb
- Phone: +442046203253
- DB backup: receptionist.db.bak (pre ID migration)

## Voice / Webhook Status
- Webhooks are live via temporary cloudflared tunnel (URL changes on restart)
- On each restart: run `cloudflared tunnel --url http://localhost:5050`, then update Retell agent webhook_url via API
- Background auto-sync runs every 3 mins as fallback
- See [project_voice_tunnel.md](project_voice_tunnel.md) for permanent tunnel TODO

## Memories
- [project_voice_tunnel.md](project_voice_tunnel.md) — Need permanent cloudflared tunnel / production server
