# Deploy — papertrail.borant.eu

Porta **8017**, dietro Caddy, sul VPS borant (`/opt/apps/papertrail`).

## Prima installazione

```bash
ssh spit@borant.eu
sudo mkdir -p /opt/apps/papertrail && sudo chown spit:spit /opt/apps/papertrail
git clone https://github.com/that-ugly-cat/papertrail.git /opt/apps/papertrail
cd /opt/apps/papertrail
cp .env.example .env
printf 'JWT_SECRET=%s\n' "$(openssl rand -hex 32)" >> .env   # poi togli la riga vuota dal template
docker compose up -d --build
```

Primo utente e workspace ITE:

```bash
docker exec -it papertrail python seed.py spit@example.org "Giovanni Spitale" "<password>"
```

Poi da `/admin` crei l'utente di Federico, e da `/w/ite/members` gli dai `admin`.

## Caddy

In `/etc/caddy/Caddyfile`:

```
papertrail.borant.eu {
    reverse_proxy localhost:8017
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Aggiornamenti

```bash
cd /opt/apps/papertrail && git pull && docker compose up -d --build
```

Le migrazioni sono additive e girano da sole all'avvio (`init_db()` in
`models.py`): nessun passo manuale, ma anche nessun rollback automatico. Le
colonne non si rinominano e non si droppano.

## Backup

Il DB è un file solo, nel volume montato:

```bash
sqlite3 /opt/apps/papertrail/data/papertrail.db ".backup '/tmp/papertrail-$(date +%F).db'"
```

## Dev locale

```bash
cd papertrail
uv venv && uv pip install -r requirements.txt
JWT_SECRET=dev COOKIE_SECURE=0 uv run uvicorn main:app --reload --port 8017
```

`COOKIE_SECURE=0` serve perché in locale non c'è TLS e il browser scarterebbe un
cookie marcato `secure`, lasciandoti in un loop di login.
