# Riconciliazione wiki ↔ PaperTrail — decisioni

Revisione manuale, pagina per pagina, con Spit (18 ago 2026).
Regola: la prosa resta nel wiki, PaperTrail prende un `Link(kind='wiki')`.
Convenzione del target: path repo-relative dentro Ono3, non URL — il template
rende `wiki` come testo, non come href.

| # | pagina wiki | esito | progetto | note |
|---|---|---|---|---|
| 1 | `!against-autonomy-beneficence-conflict.md` | esiste | **31** Against the A/B conflict | link + aggiunta Nikola Biller-Andorno come co-autrice |
| 2 | `!ai-coding-turing-test.md` | **creato** | **137** AI Coding Turing Test | `developed`/paper; Spit lead, Germani + Biller-Andorno co-autori. Pagina di giugno, posteriore al congelamento Notion — niente da riconciliare |
| 3 | `!ai-overview-hallucinations.md` | esiste | **13** ~~Google AI overviews complacency~~ → **AI Overview hallucinations** | rinominato su conferma di Spit (il titolo Notion diceva *complacency*, che è l'altro filo), summary riempito, link |
| 4 | `!beyond-misconduct.md` | esiste | **10** Beyond misconduct | link, summary, journal *Science and Engineering Ethics*; Spit aggiunto come secondo `lead` (co-lead) accanto a Germani |
| 5 | `!epistemic-paternalism-trap.md` | esiste | **6** Epistemic paternalism | link, final_title, summary, nota su origine Brocher + coordinamento submission (Hofmann) + venue *Medicine, Health Care and Philosophy*. **Aperto:** link al draft non aggiunto — `raw/pubblicazioni-in-corso/DMA - paternalism trap draft v2 (1).docx` ha il `(1)` da duplicato Windows e non esiste un v2 pulito |
| 6 | `!fragility-moral-key-terms.md` | esiste | **46** ~~NRP80 intervention~~ → **Fragility of moral key terms** | rinominato su conferma (il nome Notion era un titolo di lavoro), final_title, summary, nota su contributo equo + grant. Autori aggiunti: Germani (lead), Merten, Biller-Andorno, Franc Fritschi. Grafia *Franc* decisa da Spit fra tre varianti nel wiki; corretta la pagina viva, non `log.md` né le sessioni |
| 7 | `!gender-neutral-bathrooms.md` | **creato** | **138** Gender-neutral bathrooms and queue efficiency | `idea`/paper, solo Spit. BMJ Christmas messo in nota, non in `journal`: su unidea sarebbe un venue mai concordato che sporca le statistiche |
| 8+9 | `!modello-collasso-epistemico.md` + `…-letteratura.md` | **creato** | **139** Modello del collasso epistemico | un progetto solo, **due link wiki** (modello + rassegna): non sono due progetti. `developed`/paper, solo Spit. Germani e Ferrario restano fuori dall'authorship finché "potenziali" — annotati. Entrambe le pagine erano orfane nel grafo |
| 10 | `!opt-out-scoping-review.md` | **creato** | **140** Opt-in to opt-out scoping review (BAG) | `active`/paper. Spit lead + Biller-Andorno, Christen, Naishtat. Due link: wiki + `lssr` al workspace vivo (primo uso di `Link.kind='lssr'`) |
| 11 | `!pgt-gge-person-affecting.md` | **creato** | **141** PGT/GGE person-affecting intuitions survey | `active`/paper, Spit e Battisti entrambi `lead`. Nota sul blocco alla preregistrazione (i cinque problemi di design sollevati a maggio) |
| 12 | `!thick-bioethics.md` | esiste | **43** Thick Bioethics | link, summary, journal *Bioethics*, Nikola aggiunta come co-autrice (author line ancora incompleta, annotato). Spit conferma: affine ma distinto da #2, #114, #123 — niente fusioni |
| 13 | `ai-assisted-suicide.md` | esiste | **103** AI assisted suicide | card già completa (Frontiers in AI 2023, DOI, abstract): serviva solo il link |
| 14 | `ai-information-ethics-volume.md` | esiste | **17** ~~Routledge book~~ → **AI and Infodemic Management (Routledge volume)** | rinominato, final_title, summary, journal Routledge, link. Due note: stato capitoli (5 e 10 scoperti) e **discrepanza aperta** — nota Notion "15.03.2026 in peer review" contro luce verde Routledge a giugno |
| 15 | `digital-ghosts.md` | esiste | **22** digital ghosts | **corretto `journal`**: era *Philosophy and Technology*, è *Ethics and Information Technology* (lo dice il prefisso DOI `s10676`). Aggiunto Germani, link, nota. Audit successivo: nessun altro DOI Springer con journal incoerente |
| 16 | `disruptive-technologies-open-science.md` | esiste | **108** Open science and disruptive technologies | card completa (SEE 2024, DOI, abstract): solo il link |
| 17 | `dono-nelle-donazioni.md` | **creato** | **142** Il dono nelle donazioni | `published`/book, 2015 (anno della tesi; anno edizione Il Poligrafo non nel wiki). **Policy decisa qui da Spit: il passato chiuso entra in PaperTrail** — non si richiede più per le pagine analoghe |
| 18 | `ethos.md` | **creato** | **143** ETHOS — democratic health governance living review | `active`/paper, Spit + Naishtat. Tre link: wiki, `lssr`, `repo` (OSF jhdmp). Due note lunghe: le quattro note di metodo (fra cui il 90% dellarbitro che non vale) e il collo di bottiglia full text |
| 19 | `fakespotter.md` | esiste | **117** Disinformation Recognition Software (Fake Spotter) | trovato da Spit, non dal grep (cercavo `fakespotter` attaccato, la card scrive *Fake Spotter*). final_title, summary, journal NMI, link, due note (stato wiki obsoleto rispetto al preprint arXiv di lug; grappolo idee satellite #3 #4 #18 #19). **Aperto:** `Link(kind='preprint')` ha target `arXiv`, una stringa e non un URL → link rotto nel template |
| 20 | `future-bioethics-publishing.md` | esiste | **123** Reinvent publication system in bioethics | link, summary, 4 autori aggiunti (Fadda, Rivas, Trachsel, Biller-Andorno corresponding). Stato `submitted` **lasciato invariato**: con submission `accept` e nessun DOI, `effective_status()` mostra già *accepted* (SPEC §5). Note: accettato non ancora uscito (era dato in uscita giu 2026), tentativo a durata zero SPEC §10, e il summary precedente conservato |
| 21 | `germani-dual-nature-ai.md` | esiste | **109** AI disinformation ethics | card completa (JMIR AI 2024, DOI, abstract): solo il link |
| 22 | `germani-source-framing-bias.md` | esiste | **51** ~~LLM Pit - Narratives OpenAI/ DeepSeek/Mistral/Gro~~ → **Source framing bias in LLMs** | rinominato (il titolo Notion era tronco e irriconoscibile), Germani aggiunto, link, vecchio titolo conservato in nota |
| 23 | `gpt3-disinforms.md` | esiste | **92** AI model GPT-3 (dis)informs us better than humans | card completa (Science Advances 2023, DOI): solo il link |
| 24 | `hestia.md` | **creato** | **144** Hestia | `published`/book, 2017, Il Poligrafo, prefazione Diego Cugia. Stesso nucleo di #142, forma diversa |
| 25 | `introducing-preference-epidemiology.md` | esiste | **59** ~~Prepidemiology perspective~~ → **Introducing preference epidemiology** | rinominato, link, vecchio titolo in nota. Card già completa (IJPH 2025, DOI) |
| 26 | `mi-fa-male-la-scienza.md` | esiste | **84** Mi fa male la scienza | link + nota di rimando a **#41** (versione internazionale, `writing`). #41 resta **senza link wiki**: non ha una pagina propria, la questione se agganciarlo alla stessa è rimasta aperta |
| 27 | `oa-value-extraction.md` | esiste | **14** OA value extraction full paper | link su #14 (il wiki descrive il full paper). Germani e Biller-Andorno aggiunti **sia su #14 sia su #21** (il precis su Nature). Note: CRediT completi, e la **questione aperta** dichiarata dal wiki sul rapporto con #10 Beyond misconduct |
| 28 | `patient-derived-taxonomy-harm.md` | esiste | **44** ~~DIPEx AI~~ → **Patient-derived taxonomy of healthcare harm (Ritzmann)** | rinominato su indicazione di Spit («è il paper Iris Ritzmann»): «DIPEx AI» era troppo generico con #90/#93/#128 in giro. final_title, summary, link, +3 autori (Naishtat, Ritzmann, Biller-Andorno) |
| 29 | `rasita-emotional-prompting.md` | esiste | **111** ~~SDPI - politeness, AI, disinformation~~ → **Emotional prompting amplifies disinformation in LLMs** | rinominato (il vecchio diceva *politeness* per *emotional manipulation*), +Rasita Vinay (prima autrice) e Biller-Andorno, link |
| 30 | `redaelli-critical-thinking.md` | esiste | **118** Critical thinking skills and disinformation recognition | link, +Simone Redaelli (primo autore). **Correzione verso il wiki**: la pagina diceva «Frontiers in Psychology (o simile)», è *Frontiers in Education* (DOI feduc) — corretta la pagina |
| 31 | `religious-influence-pluriversalism.md` | esiste | **114** Bioethics, religion, pluriversalism | card completa (Bioethics 2025, DOI): solo il link |
| 32 | `serious-games-health-governance.md` | esiste | **30** ~~ERC game concept~~ → **Playing Democracy (serious games)** | rinominato, final_title, summary, link, +4 autori (Molnár-Gábor, Prainsack, Germani, Biller-Andorno corresponding). Note: riorientamento post-AJOB di lug 2026 e target ORE in standby. **Aperto:** submission Heliyon a durata zero, la nota ha le date vere ma «review submitted» è ambiguo |
| 33 | `speak.md` | esiste | **98** ~~SPEAK - Talk2UZH ICU preferences~~ → **SPEAK — What makes intensive care acceptable?** | rinominato (il titolo Notion impastava studio e piattaforma), summary, +Naishtat (prima autrice) e Biller-Andorno, tre link: wiki, `preprint` Zenodo, `repo` OSF |
| 34 | `talk2uzh-stt-evaluation.md` | **creato** | **145** Talk2UZH — speech-to-text evaluation in health surveys | `writing`/paper, npj Digital Medicine, **13 autori** in ordine (Baumer lead, Spit co-autore). Distinto da #98 su indicazione di Spit. **Scadenza 19 ago 2026** in nota: il modello `Deadline` esiste ma non è cablato nella UI |
| 35 | `wandering-wombs-endometriosis.md` | esiste | **24** Wandering Wombs | final_title (titolo della revisione), summary, journal, link, +4 autori (Germani, Bonato, Biller-Andorno, Barış corresponding). **Ricostruita la submission mancante**: MHCP, invio 15.12.2025 → `reject_after_review` 09.04.2026, 115 giorni. Esisteva solo come prosa nelle note, quindi non contava in nessuna statistica (SPEC §9). Provenienza dichiarata in `Submission.notes` |

## Da chiudere

- **#117 FakeSpotter** — `Link(kind='preprint')` ha target `arXiv`, una stringa e non un URL: `preprint` è fra i kind cliccabili, quindi produce un link rotto. Serve lID arXiv.
- **#86 COVID Eyam plague paper** — `journal` scritto `Medicine health care and philosopy` (refuso + minuscole). È la stessa rivista di #24 e #6: tre grafie per un venue solo, che è il guaio descritto in `models.py`.
- **#17 Routledge volume** — nota Notion «15.03.2026 in peer review» contro luce verde Routledge di giugno: da chiarire se si riferiva alla proposta.
- **#30 Playing Democracy** — submission Heliyon a durata zero; la nota ha le date vere ma «review submitted 24.02.2026» è ambiguo fra invio e ritorno referee.
- **#6 Epistemic paternalism** — link al draft non aggiunto: `DMA - paternalism trap draft v2 (1).docx` ha il `(1)` da duplicato Windows e non esiste un v2 pulito.
- **#41 MFMLS International** — nessun link wiki: non ha una pagina propria, e non è deciso se agganciarlo a quella delledizione italiana.
- **#43 Thick Bioethics** — author line incompleta («Nikola + da completare»).
- **#44** — ordine autori e affiliazioni da confermare.
- **#123 Future of Bioethics Publishing** — accettato a *Bioethica Forum* ma non ancora uscito, era dato in uscita a giugno 2026.
- **#145 Talk2UZH** — accordo alla submission entro il **19 ago 2026**.
- **Modello `Deadline`** — definito ma non cablato: zero righe, nessuna rotta in `main.py`. Finché è così le scadenze vivono nelle note.
