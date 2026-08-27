# PaperTrail

Tracking di progetti di ricerca da idea a paper pubblicato, per gruppi di ricerca.

Un progetto entra come idea e ne esce come pubblicazione, passando per il lavoro,
la scrittura e — quasi sempre più di una volta — la submission. PaperTrail tiene
quella traccia: chi ci lavora, a che punto è, da quanto tempo, dove sta il
materiale, e quante volte è stato rimbalzato prima di trovare casa.

## Cosa lo distingue da una board qualsiasi

**Il tempo si registra da solo.** Ogni cambio di stato lascia un evento con data e
autore. Le domande che di solito richiedono di ricordarsi a mano diventano viste:
cosa è fermo da più di tre mesi, da quanto una submission è in review, quanto ci
mette mediamente un journal a rispondere.

**La submission è un ciclo, non una casella.** Un paper può essere rifiutato,
rivisto e ripresentato altrove. Ogni tentativo è una riga con journal, data ed
esito, e la storia completa resta leggibile. E sono attese diverse, non una:
sulla scrivania di un editor un paper può tornare indietro domani con un desk
reject, dai referee ci mette mesi — quindi due colonne, `Submitted` e
`Under review`, ma un tentativo solo, con lo stesso venue e lo stesso orologio.

**Accettato non vuol dire pubblicato.** Fra la lettera e il DOI ci sono bozze,
embargo e un fascicolo che si riempie quando si riempie: mesi in cui il paper è
vinto e non esiste, e in cui a essersi fermata è la coda di qualcun altro.
`Accepted` è una colonna sua, ed è l'unica fase avanzata che **può ancora
diventare dormiente** — un paper accettato che non esce mai è esattamente ciò che
deve tornare a galla.

**Le idee non muoiono in fondo alla lista.** Ciò che non si muove da abbastanza
tempo viene marcato dormiente e torna a galla, invece di sedimentare in silenzio.

**Ogni progetto è collegato al resto.** Wiki, file, bandi, review sistematiche:
un progetto punta alle cose che lo riguardano invece di essere un'isola.

**Il bollino giallo.** Un pallino su una card, un click, e quel progetto è fra
quelli su cui devi mettere il naso. È privato — lo vedi solo tu, anche sui paper
degli altri — e non cambia niente di ciò che il gruppo vede: non fa apparire il
progetto vivo, non ti mette a seguirlo, non chiede il permesso di scrittura.
Filtro sulla board, scheda **Flagged** in «My work», e leggibile via MCP, così
«cosa devo guardare» ha una risposta anche fuori dal browser.

## Accesso

Ogni **workspace** è un gruppo di ricerca. Ogni persona ha, per ciascun
workspace, uno di tre livelli: nessun accesso (il workspace non esiste, per lei),
sola lettura, oppure scrittura. Chi è `admin` di un workspace gestisce anche i
membri di quel workspace, senza passare dall'amministratore di sistema.

In più, **ogni utente ha un workspace personale**, creato insieme all'account e
visibile solo a lui. Serve al lavoro che non è di nessun gruppo: un libro, una
tesi vecchia, un'idea appena annotata. Non è un posto separato con regole sue —
è un workspace come gli altri, quindi condividere dopo significa aggiungere il
gruppo, non spostare il progetto.

## Stato

**In uso reale** su [papertrail.borant.eu](https://papertrail.borant.eu) dal 18
agosto 2026. 136 progetti migrati da Notion, più quelli aggiunti riconciliando il
wiki.

C'è: login e ruoli per workspace, workspace personale per utente, progetti
condivisibili fra gruppi, board kanban con drag-and-drop, ciclo di submission
completo (tentativi, giri di revisione, transfer), `Submitted`, `Under review` e
`Accepted` come colonne separate, bollino giallo per utente, vista «My work» trasversale,
Hall of done per anno, cestino, layer MCP con 16 tool, audit read-only.

I collegamenti all'ecosistema esistono come `Link`: `wiki` verso le pagine del
wiki di Spit, `lssr` verso i workspace delle review, più `doi`, `preprint`,
`repo`, `grant`, `file`, `url`.

Non c'è ancora: le **deadline** (il modello c'è, l'interfaccia no — finché è così
le scadenze vivono nelle note), statistiche sulle latenze per journal in
interfaccia, ricerca semantica sulle idee (quella che c'è è lessicale, e lo
dichiara), matching automatico con Grant Radar.

Dettagli architetturali e roadmap in `SPEC.md` (locale, non versionato).
Installazione e deploy in `DEPLOY.md`.

## Stack

FastAPI, Jinja2, SQLAlchemy, SQLite. Docker, porta 8017.

## Facoltativo: dietro un gate SSO

`AUTH_MODE=gateway` sostituisce il login dell'app con un gate `forward_auth` a
monte: si arriva già riconosciuti, `/login` si spegne da sé, e le persone si
ritrovano per subject immutabile invece che per indirizzo email.

**Due cose non si muovono, ed è il punto.** `/mcp*` resta fuori con la sua
chiave per-utente, `/mcp/k/{chiave}` compreso. E soprattutto **l'autorizzazione
resta qui**: il gate dice *chi sei*, `workspace_dep` continua a decidere *cosa
puoi toccare*, e un profilo che arrivasse senza righe in `Membership` non
vedrebbe nessun workspace. Il modo peggiore di sbagliare la configurazione è
quindi una schermata vuota, non una fuga.

Nessun secondo fattore: le colonne `totp_*` esistevano da uno schema vecchio,
non sono mai state collegate a una rotta, e sono state tolte. Se un giorno
servisse, lo mette il gate come policy — senza una riga qui.

`local` resta il default e pienamente supportato. Dettagli in `DEPLOY.md`.
