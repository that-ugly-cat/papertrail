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
colonne non si rinominano e non si droppano. Le **tabelle nuove** compaiono allo
stesso modo, da `create_all()`, quindi una funzione che ne porta una non richiede
niente in più di un `up -d --build` — controlla che ci sia, non darlo per fatto:

```bash
docker exec papertrail python -c "import sqlalchemy as sa, models; print(sorted(r[0] for r in models.engine.connect().execute(sa.text(\"select name from sqlite_master where type='table'\"))))"
```

**Se `git pull` si ferma su modifiche locali.** Succede quando qualcosa è stato
corretto a mano direttamente qui. Prima di scartare, guarda **cosa** sia: il file
può essere in CRLF, e allora il diff è un muro di rumore che nasconde le poche
righe vere.

```bash
git diff --ignore-cr-at-eol --stat          # quante righe sono davvero cambiate
git fetch origin
git diff --ignore-cr-at-eol origin/main -- <file>   # vuoto = non perdi niente
```

Vuoto significa che la modifica è già in history e la copia locale non contiene
nulla di unico: `git checkout -- <file>` e poi pull. Se **non** è vuoto, sul
server c'è lavoro che non esiste altrove, e va portato via prima di toccarlo.

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

## Dietro un gate SSO (`AUTH_MODE=gateway`)

Facoltativo, e spento se non lo si accende. In `gateway` PaperTrail smette di
chiedere la password e legge gli header d'identità messi da un gate
`forward_auth` davanti. `/login` reindirizza alla home, e «esci» passa da
`BORANT_LOGOUT_URL` così la sessione centrale muore col cookie locale.

**Quello che non cambia, ed è la parte importante:** l'autorizzazione resta qui.
Il gate dice *chi sei*; `workspace_dep` continua a decidere *cosa puoi toccare*,
e un profilo senza righe in `Membership` non vede nessun workspace. Il modo
peggiore di sbagliare la mappatura è quindi una schermata vuota, non una fuga.

**E `/mcp` resta fuori dal gate**, con la sua chiave per-utente: un client
modello non ha browser né cookie, e metterlo dietro una sessione di dominio
vorrebbe dire spegnerlo. `/mcp/*` copre anche `/mcp/k/{chiave}`.

**`local` resta il default.** Un'app che crede a `X-Borant-Sub` senza niente
davanti fa entrare chiunque spedisca quell'header.

```
papertrail.borant.eu {
    @pubbliche path /healthz /static/* /mcp /mcp/* /login /logout
    handle @pubbliche {
        import noforge
        import nocookie
        reverse_proxy localhost:8017
    }
    handle {
        import borantid
        reverse_proxy localhost:8017
    }
}
```

**Qui non c'è un secondo fattore, ed è una scelta.** Ce n'era uno abbozzato
nello schema — due colonne `totp_*` mai collegate a una rotta — e la tabella
lasciava intendere una protezione che l'app non applicava: sono state tolte. Il
pannello `/admin` crea utenti e workspace, non apre dati che il resto dell'app
non apra già, quindi non merita un gradino in più.

Se un giorno servisse, **lo mette il gate** e non questo codice: è una `policy`
con `path_prefix` e `level = two_factor` nel suo pannello, senza una riga qui e
senza un reload di Caddy.

**Prima di accendere, lega gli utenti esistenti e leggi il report:**

```bash
docker exec papertrail python map_borant.py --map tu@example.org=01ABC…
docker exec papertrail python map_borant.py --report
```

`BORANT_TRUSTED_PROXY` è il secondo lucchetto e l'impostazione che si sbaglia.
Sotto Docker il container non vede `127.0.0.1` ma il gateway di una rete bridge.
Si legge dalla realtà:

```bash
curl -s -o /dev/null http://127.0.0.1:8017/healthz && docker logs papertrail 2>&1 | tail -1
```

Rollback, due righe e nessuna migrazione di dati:

```bash
sed -i 's/^AUTH_MODE=gateway/AUTH_MODE=local/' .env
docker compose up -d
```

## The landing, the home, and the role hint

Same shape in every app of the perimeter, so there is nothing to remember per
tool.

**`/` is a public showcase and never asks who is reading it.** Not laziness: on
the public branch of the reverse proxy the `X-Borant-*` headers are stripped by
construction, so a branch on the user is always false behind the gate and
sometimes true without one — the same page with two behaviours. By not asking,
the page is identical in both modes and one button covers all four cases:
gated or standalone, already signed in or not. It also shows no internal
counts: anyone can read it.

**The app lives at `/app`**, which is gated, and the showcase's button
points there — not at `/login`, which on a page that can never recognise anyone
would close a loop with no way in, and not at the gate's own URL, which would
work and would wire Borant ID into an app that must keep running without it.

**The role hint is honoured, and its vocabulary is one word: `admin`.** Note
what it is *not*: the domain role here is per workspace — read, write, admin on
*which* one? — and a global hint at first provisioning cannot answer that. This
`admin` is the other flag, the one that opens `/admin/users`. A profile created
as an admin this way is logged loudly.

**A page that needs an identity fails closed.** In `gateway` an unauthenticated
request does *not* redirect to `/login` — the app switches that route off in
this mode and sends it back, so the two would bounce forever. Production never
shows it because the gate intercepts first, but a wrong proxy matcher would
produce a spin instead of an error, and a loop is far harder to diagnose than a
status code. The answer is a 503 naming what the operator should check, because
a request arriving with no identity means the gate did not run.
