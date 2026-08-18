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
esito, e la storia completa resta leggibile.

**Le idee non muoiono in fondo alla lista.** Ciò che non si muove da abbastanza
tempo viene marcato dormiente e torna a galla, invece di sedimentare in silenzio.

**Ogni progetto è collegato al resto.** Wiki, file, bandi, review sistematiche:
un progetto punta alle cose che lo riguardano invece di essere un'isola.

## Accesso

Ogni **workspace** è un gruppo di ricerca. Ogni persona ha, per ciascun
workspace, uno di tre livelli: nessun accesso (il workspace non esiste, per lei),
sola lettura, oppure scrittura. Chi è `admin` di un workspace gestisce anche i
membri di quel workspace, senza passare dall'amministratore di sistema.

## Stato

**In uso reale** su [papertrail.borant.eu](https://papertrail.borant.eu) dal 18
agosto 2026, con 136 progetti migrati da Notion.

C'è: login e ruoli per workspace, progetti condivisibili fra gruppi, board kanban
con drag-and-drop, ciclo di submission completo (tentativi, giri di revisione,
transfer), vista «My work» trasversale, Hall of done per anno, cestino, layer MCP
con 11 tool, audit read-only.

Non c'è ancora: deadline, statistiche sulle latenze per journal in interfaccia,
ricerca semantica sulle idee, collegamento a Grant Radar e LSSR.

Dettagli architetturali e roadmap in `SPEC.md` (locale, non versionato).
Installazione e deploy in `DEPLOY.md`.

## Stack

FastAPI, Jinja2, SQLAlchemy, SQLite. Docker, porta 8017.
