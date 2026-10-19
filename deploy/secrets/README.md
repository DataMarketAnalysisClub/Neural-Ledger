# Data key secret (`NL_DATA_KEY`)

The API seals the personal data it stores in SQLite with AES-256-GCM. The key that does it must never sit on
the same volume as the database. In a deployment it is a Docker secret, mounted at `/run/secrets/nl_data_key` by
[`docker-compose.data-key.yml`](../../docker-compose.data-key.yml).

Never commit a real key: this directory ignores everything but this README and the `.example` file.

## Make a key (once per server)

```sh
sudo install -d -m 700 /opt/neural-ledger/secrets
( umask 077; openssl rand -hex 32 > /opt/neural-ledger/secrets/nl_data_key )
sudo chown 10001 /opt/neural-ledger/secrets/nl_data_key && sudo chmod 400 /opt/neural-ledger/secrets/nl_data_key
```

The file holds 64 hex characters and nothing else (a trailing newline is fine); `nl_data_key.example` shows the
shape. uid 10001 is the `app` user of `backend/Dockerfile`, which must be able to read the mounted file.

**Back the key up somewhere else than the database backups** (a password manager, a sealed envelope). Losing it
loses every statement, profile and account; storing it next to the database backups undoes the separation.

## Use it

```sh
export NL_DATA_KEY_SECRET_FILE=/opt/neural-ledger/secrets/nl_data_key
docker compose -f docker-compose.yml -f docker-compose.data-key.yml up -d --build
```

`NL_DATA_KEY_SECRET_FILE` is read by Compose only (to find the file); the container sees the key at
`/run/secrets/nl_data_key`. Compose can also create the secret from a variable in the operator's shell instead of
a file (`environment: NL_DATA_KEY_VALUE` in place of `file:` under `secrets.nl_data_key`), so the key is never on
the host's disk; then it must be provided on every `up`.

An existing database written with the old offline key file is moved with `neural-ledger migrate-data`
(docs/SECURITY.md, "Key management").
