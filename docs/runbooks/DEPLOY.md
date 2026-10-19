# Public demo deployment (nixbox, Cloudflare Tunnel)

How https://neural-ledger.dmac.cl is served: one server (nixbox), Docker Compose, no published port. **Offline mode only**: scripted model, rules decision chain, sandbox bank, no LLM keys. Anything live or staging needs Cloudflare Access first (`docs/SECURITY.md`, "Public demo deployment").

## Architecture

```
browser --https--> Cloudflare edge: TLS, rate limit rule, DNS (proxied CNAME neural-ledger -> <tunnel-id>.cfargotunnel.com)
                        ^
                        | outbound QUIC, opened by the server (no inbound port)
                   cloudflared (tunnel "neural-ledger", remotely managed)
                        | http, Compose network neural-ledger_default
                        v
                   web:3000  nginx: UI, HTTPS redirect, security headers, visitor IP from CF-Connecting-IP
                        | /api/* -> /*
                        v
                   api:8000  uvicorn, SQLite in volume neural-ledger_ledger-data
```

- `docker-compose.yml`, `web/nginx.conf` and the Dockerfiles are the official delivery and CI path and are not edited. Everything for this deployment lives in `deploy/`:
  - `deploy/docker-compose.deploy.yml`: an override that removes every host port (`ports: !reset []`), adds `restart: unless-stopped`, mounts `nginx.deploy.conf` read-only over the web image's config, adds a web healthcheck and the `cloudflared` service (pinned version, token from `.env.tunnel`).
  - `deploy/nginx.deploy.conf`: `web/nginx.conf` plus a 301 to https when `X-Forwarded-Proto` is `http`, security headers in every location (HSTS without `includeSubDomains`, nosniff, `X-Frame-Options: DENY`, `Referrer-Policy`, a strict CSP), and the visitor's address from `CF-Connecting-IP` for `X-Real-IP`/`X-Forwarded-For`. **Keep its locations in sync with `web/nginx.conf`** when that file changes.
- Tunnel ingress (Cloudflare, remotely managed): `neural-ledger.dmac.cl -> http://web:3000`, everything else `http_status:404`.
- Cloudflare settings are scoped to this hostname only. Never change zone-wide settings for it (Always Use HTTPS, Bot Fight Mode, Under Attack) and never touch the other hostnames or tunnels of the zone.

## Server layout

```
/opt/neural-ledger/app      the deployed commit, from git archive (not a working checkout); the Compose project directory
/opt/neural-ledger/app/.env       mode 600, read by api
/opt/neural-ledger/app/DEPLOYED_COMMIT
/opt/neural-ledger/deploy   docker-compose.deploy.yml, nginx.deploy.conf, .env.tunnel (mode 600, read by cloudflared only)
```

Relative paths in the override resolve from the project directory (`app/`), hence `../deploy/...`. Back up any file under `/opt/neural-ledger` to `~/backups` before editing it.

`app/.env` holds only:

```ini
NL_APP_ORIGINS=https://neural-ledger.dmac.cl   # without it every POST (sign-in included) gets ORIGIN_REJECTED
NL_COOKIE_SECURE=true
NL_HMAC_SECRET=<openssl rand -hex 32>          # the development default is public in this repository
```

No LLM key and no `NL_LLM`, `NL_DECISION_CHAIN`, `NL_CLASSIFIER` or `NL_PII_DETECTOR`: `/health` must report `"mode":"offline"`. The tunnel token never goes in `app/.env`, because the api loads that whole file.

On nixbox, `127.0.0.1:3000` belongs to another service: never run `app/docker-compose.yml` without the override there.

## Deploy or update

```sh
# from a local clone: ship the commit to deploy
git archive <commit> | ssh nixbox 'rm -rf /opt/neural-ledger/app.new && mkdir /opt/neural-ledger/app.new && tar -x -C /opt/neural-ledger/app.new'
# on nixbox: keep .env, swap the tree, record the commit
cd /opt/neural-ledger && cp -p app/.env app.new/.env && echo <commit> > app.new/DEPLOYED_COMMIT \
  && mv app ~/backups/neural-ledger-app-$(date +%Y%m%d-%H%M%S) && mv app.new app
alias nlc='docker compose -p neural-ledger -f app/docker-compose.yml -f deploy/docker-compose.deploy.yml'
nlc config | grep -nE 'ports:|published' || echo "no ports"   # must print "no ports"
nlc up -d --build
```

The `ledger-data` volume (audit chain, sandbox bank, accounts) survives rebuilds. Never add `-v` to `down` and never prune.

## Verify

```sh
nlc ps                                                        # api and web healthy, cloudflared Up
nlc logs cloudflared | grep -E 'Registered tunnel connection|ERR'  # 4 registrations; ERR only around a stop or restart
curl -s https://neural-ledger.dmac.cl/api/health                # "mode":"offline", "audit_chain_ok":true
curl -s https://neural-ledger.dmac.cl/ | grep '<div id="root">'
curl -sI http://neural-ledger.dmac.cl/                          # 301 to https
curl -sI https://neural-ledger.dmac.cl/                         # HSTS, CSP, nosniff, X-Frame-Options, Referrer-Policy
sudo ss -tlnp | grep -E ':(3000|8000)\b'                        # no Docker listener (127.0.0.1:3000 is another service)
```

- From another LAN machine, `curl -m 5 http://<nixbox-lan-ip>:3000/` and `:8000` must time out or be refused.
- In a browser, sign in with "Explore as Camila": the overview shows the E01 headline and the console has no CSP violation except Cloudflare's Web Analytics beacon (`static.cloudflareinsights.com`), which is injected zone-wide and blocked on purpose (no third-party script in the demo).
- The HTML must not carry Cloudflare Email Obfuscation (`email-decode`, `[email protected]`). It is on for the zone, but the app shell has no address.
- Rate limit: six POSTs to `/api/v1/auth/demo-session` within 10 s get a `429` from Cloudflare; the normal demo flow does not.
- After `nlc restart`, everything comes back without manual steps (`restart: unless-stopped`, `docker.service` enabled).

## Rate limiting

The free plan has a single rate limiting rule for the zone, shared with brief.dmac.cl. Neural Ledger is an extra `or` clause on it, so edit that rule only (PATCH the rule, never PUT a new entrypoint) and save the previous JSON to `~/backups` first:

```
(http.host eq "neural-ledger.dmac.cl" and http.request.method eq "POST"
 and http.request.uri.path in {"/api/v1/auth/signin" "/api/v1/auth/signup" "/api/v1/auth/demo-session"})
```

5 requests per 10 s per IP and colo, block for 10 s. Only the credential endpoints are covered: the UI sends several POSTs in a row (profile queries, plan, chat), and one 5-per-10-s threshold over all of `/api/` would block a normal demo. The API keeps its own per-IP limits (G07), which see the visitor's address through `CF-Connecting-IP`.

## Rollback

- **Take it offline at once:** `nlc stop cloudflared`. Cloudflare answers 1033 and nothing is exposed; `nlc start cloudflared` brings it back.
- **Full removal:** `nlc down` (keeps the volume). In Cloudflare, delete only the `neural-ledger` CNAME and the `neural-ledger` tunnel, never those of dmac.cl, app or brief. Restore the rate limiting rule from its `~/backups/cf-ratelimit-entrypoint-*.json` by PATCHing the rule back to its previous expression and description.
- **Bad release:** move the previous tree back from `~/backups/neural-ledger-app-*` (keep `.env`) and `nlc up -d --build`.

## Rotate the tunnel token

Rotate it on any doubt (it lets anyone serve content on the hostname), and when someone with server access leaves.

1. Cloudflare dashboard, Zero Trust > Networks > Tunnels > `neural-ledger`: refresh (rotate) the token. Connectors using the old one stop being accepted on reconnect.
2. On nixbox, write the new token straight to the file, never through chat, shell history or command arguments. Either use the API, as at creation (`GET /accounts/<account>/cfd_tunnel/<tunnel-id>/token`, with the response written by a script to the file), or paste it with an editor:
   ```sh
   cp -p /opt/neural-ledger/deploy/.env.tunnel ~/backups/env.tunnel-$(date +%Y%m%d-%H%M%S).bak
   ( umask 077; read -rs T; printf 'TUNNEL_TOKEN=%s\n' "$T" > /opt/neural-ledger/deploy/.env.tunnel; unset T )
   ```
3. `nlc up -d --force-recreate cloudflared` and check for four registrations in the logs.
4. Delete the backup of the old token once the new one works.
