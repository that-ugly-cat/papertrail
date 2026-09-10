# PaperTrail — User Guide

PaperTrail tracks a research project from the first note to the version of record: which stage it is in, who is driving it, where it was sent, how that went, and the number no spreadsheet ever keeps honestly — how long it has been sitting there. It is not a list of things to do. It is a record of **where each piece of work stands**, and the history underneath it is written by the tool as you work, not by you remembering to write it.

---

## 1. Getting in

`papertrail.borant.eu` opens on a page that never looks at who is reading it. **Enter** takes you to the app, which sits behind **Borant ID** — the single sign-on shared by the borant.eu tools, so if you already use one of the others you already have an account.

There is no self-registration inside PaperTrail: an account either appears on your first arrival through the gate, or a system admin creates it for you — today that means asking Spit.

The first screen after login is **Workspaces**, and it may be empty. Nothing is broken and nothing is being hidden from you by accident: **sight comes from membership**, and a profile with no membership sees no workspace at all. Ask an admin of the group to add you — that is one row, and it takes a minute.

**Profile** holds your name, your MCP keys (§10) and your password. Being a *system admin* — the flag that lets someone create accounts and workspaces — is separate from access to content: an admin with no membership sees the same empty screen as anyone else.

## 2. Workspaces, roles, and the personal one

A **workspace** is a research group, not a person: it holds projects, its own member list and its own trash. Two people in the same group share one board and filter it by author, because splitting a group per person would make a co-authored paper into two cards.

Your role is per workspace:

- **not a member** — the workspace does not exist for you, and its URL answers **404 rather than 403**, because a 403 confirms that something is there and pre-submission work should be indistinguishable from work that never existed. There is no "no access" level to set: you remove the row.
- **read** — sees everything, writes nothing, not even a note.
- **write** — creates and edits projects, statuses, notes, submissions, links.
- **admin** — write, plus the workspace's own member list, so adding a doctoral student does not have to go through the system administrator.

Every account also gets a **personal workspace**, created with it and visible only to you. It is where work that is nobody's group lives: an idea jotted down at a conference, a book, a thesis from 2015. It is a plain workspace with the same rules — `personal` is a label for the interface, never a privilege.

A project can belong to **several workspaces at once** (tick them on the project page). One of them is its home — the one in its URL — and the others are additions, so a shared paper is one object and not two copies drifting apart. You need `write` at both ends to change that sharing, you cannot untick every box (a project with no workspace has no access rule at all), and your role on a shared project is **the best one you hold across its workspaces**, so the same button does not work or fail depending on which board you came in from.

The dormancy threshold (§8) is a per-workspace setting of **180 days**, and there is no form for changing it yet.

## 3. The board, and the status vocabulary

The board is eleven columns, left to right, in the order work moves. Drag a card to move it; you need `write`. Reordering cards *within* a column writes nothing to the history — deliberately, because staleness and dormancy are read from that history and tidying a column must not make a dead project look alive.

| Status | What it means |
|---|---|
| **Idea** | Written down, nothing started. |
| **Developed** | Thought through — a design, a plan, an abstract. |
| **Active** | Being worked on: data collection, analysis, whatever it is. One status, because nobody opens a tracker while collecting data; the detail goes in a note. |
| **Writing up** | Being written. |
| **Ready** | Finished and not yet sent. |
| **Submitted** | On an editor's desk. It can come straight back tomorrow as a desk reject. |
| **Under review** | With the reviewers. Slower, and it usually ends in a revision — the same attempt, the same clock, a different kind of waiting. |
| **In revision** | The reviews came back and the paper is with you. The attempt is still open at that venue. |
| **Accepted** | Won, and not out: proofs, embargo, an issue that fills up when it fills up. Nobody here controls that queue. |
| **Published** | Out, with a DOI. |
| **Archived** | Abandoned, withdrawn, or done with. |

Crossing into **Submitted** or **Under review** from outside asks for the venue and the date, because that is the moment the information exists; leaving them asks what happened. Moving *between* those two asks nothing and opens nothing — same venue, same attempt, same clock.

Filters, with their counts: free-text search over titles and summary, one author, **dormant only**, **flagged** (your dots, §5), and **status mismatch** (§7). Each card carries the badges that matter: dormant, status mismatch, number of notes, output type when it is not a paper, publication year.

## 4. The project page

One **Save**, under the title, for the whole details block.

- **Working title** and **Final title** — what you call it while writing, and what it was published as. Lists show the second wherever it exists.
- **Journal / venue** — read this one twice, because it is the field that misleads people. It records **the venue associated with the project, in practice the last one it was at, and never the one you are aiming for**. Nothing writes it when you open a submission and nothing clears it when an attempt fails, so on a paper that has bounced it names where the paper *has been*. Where it is *now* is read from the submissions; where you intend to send it next belongs in a note.
- **DOI** — not a bibliographic detail but a switch: any value here makes the project read as *Published* everywhere, overriding the column. A preprint DOI therefore announces a publication that did not happen — preprints are links of kind `preprint`, and the web form does not check this for you yet, so it is on you.
- **Type** — paper, book, book chapter, media piece, LinkedIn post, other. It exists because "attempts to publication" compares nothing useful when a Routledge book and a LinkedIn post are the same kind of row.
- **Year**, **Summary**.

**Notes** take Markdown, and the interface has no edit and no delete for them: a note is a record of what was thought on a date, and the "Bigger editor" button is there because the useful ones are long. **Links** attach the rest of the world — `wiki`, `file`, `grant`, `lssr`, `doi`, `preprint`, `url`, `repo`; only `http(s)` targets render clickable, so a row holding a bare title stays text instead of pointing nowhere. A link ticked **only me** is yours: nobody else sees it or can remove it, and the history records that a link was added without copying the target that was the private part.

**History** lists every event with its date and whoever caused it. **Delete this project** is reversible — it disappears from every board and waits in the workspace **Trash**, which anyone with `write` can restore from. Destroying it for good is a workspace admin's action and the only irreversible one in the tool.

## 5. Authors, involvement, and the yellow dot

Three different questions, kept in three places on purpose.

**Authors** are the bibliography: names from a shared people registry (so a co-author who will never have an account still exists), with a role of lead, co-author, PI or supervisor. Pick from the autocomplete rather than retyping — the same person spelled twice is two people in every count.

**On my board** is the work list: *I lead this* or *Watching*. It is not derived from authorship, because since the Crossref import there are papers with twenty-one authors that nobody here is driving, and because watching a paper you did not write has no home under any derived scheme. `read` access is enough to set it — keeping an eye on a colleague's paper must not require the right to change it.

The **yellow dot** is *this one needs my nose in it*: one click, top-right of any card, no dialog. It is private — you see your own dots, on other people's papers included — it needs only `read`, and it writes nothing to the history, because a private mark that made a project look alive to the whole workspace would be a bug wearing the costume of a feature. The dot can carry a "why" inside the project page; the card stays one click, since a dot you have to explain is a dot you stop using. All of them together sit in **My work → Flagged**.

## 6. Submissions

A **submission** is one attempt at one venue: venue, attempt number, date sent, outcome, date of the outcome. A paper rejected by one journal and resubmitted to another is several rows, not several statuses, and the whole chain stays readable.

**One open attempt at a time.** Record the outcome of the live one before opening another: two open rows would leave the older one pending for ever, silently shadowing every later outcome.

| Outcome | Meaning | Attempt |
|---|---|---|
| in review | Nothing decided yet; the day count runs. | open |
| desk reject | Back from the editor without review. | closed |
| major revision / minor revision | Reviews back, resubmission wanted. | **stays open** |
| reject after review | Rejected after peer review. | closed |
| accepted | Won. The card goes to **Accepted**, not Published. | closed |
| withdrawn | You took it back. | closed |
| transferred | A cascade transfer to a sister journal, with no rejection in between. Recording that as "rejected" would libel the editor and distort the venue's statistics. | closed |
| outcome not recorded | Closed, and nobody wrote down how. Honest, and excluded from any latency. | closed |

A revision **does not end the attempt**: it is recorded as a dated line on that attempt, the paper is still at that venue, the clock keeps running, and moving the card back into Submitted resubmits the *same* attempt to the same editor instead of starting a new one.

The outcome form asks for the **date on the letter**, which is not the date you got round to typing it in. Left empty it defaults to today, and since every duration in this tool is a subtraction of two dates, that is exactly how a latency starts lying. Fill it in whenever you know it.

**Correct venue or dates** (and **Edit history** for closed attempts) is kept separate from recording an outcome, so that fixing a typo is not logged as an editorial decision. And **preprints are not submissions**: posting to arXiv or OSF happens in parallel with the real attempt, so it goes in as a link.

## 7. Declared status against what the record says

Status is **declared up to Ready and effective past it**. The card computes a label from the submissions and the DOI: a DOI reads as *Published*; an open attempt shows the venue and the days it has been out; an attempt still open while the card sits in Writing up or Active reads as *In revision*, because the paper is at that venue and back in your hands; a last outcome of `accept` with no DOI reads as *Accepted*; a closed rejection leaves *bounced from <venue>*.

When the declared status and the record disagree, PaperTrail **says so and overwrites neither**: the card gets a **status mismatch** badge, the project page a banner, and the board a filter with the count. The two common ones are *Ready* with an attempt still open (you cannot be ready to submit something already under review) and *Accepted* with a DOI (it is out — move it). Correct whichever of the two is wrong; the flag is there because a note gets written and a card does not get moved.

## 8. Time, and the numbers to distrust

Every status change, note, submission, outcome and field edit stamps an event with its date and its author. Nothing about time asks you to remember anything: the open attempt shows the days it has been out, closed attempts show sent → decided with the gap, and the project page shows the date of the last event of any kind.

**Dormant** is computed, not a status: no event at all for the workspace's threshold (180 days). Published and Archived are exempt — a published paper has nowhere left to go. **Accepted is not exempt**, because an accepted paper that never appears is the thing most worth surfacing, and the only case where the stall is someone else's queue.

Two numbers to distrust, both about history that was reconstructed rather than recorded. An attempt whose sent date and outcome date are the same day is not a lightning response, it is a **missing date** — those rows say so in their own notes, and any statistic about durations has to drop them. And for anything predating the migration from Notion, the timeline was rebuilt from page timestamps; the review latencies of already-published papers are not recoverable.

## 9. My work, and the hall of done

**My work** cuts across every workspace you belong to, with five tabs and their counts: *On my board* (what you lead or watch), *I lead*, *Watching*, *Flagged*, and *My name is on* — the last being a bibliography rather than a work list. Each card still belongs to its own workspace and keeps its rules there, so a card from a workspace where you only read will not drag.

Creating a project from here without choosing a workspace puts it in your **personal** one and makes you lead author, which is the point: writing a thought down should not begin by deciding which research group owns it.

The **Hall of done** shows published work as cards grouped by year, for a workspace or for you. It reads the *Published* column, so a project that has a DOI but is still parked in another column reads as Published on its card and does not appear here — one more reason to move it.

## 10. Working from a chat (MCP)

If you work with an AI assistant, PaperTrail can be plugged into it, and the question it answers best is the one nobody remembers to ask: *what is stuck?*

**Getting a key.** Profile → MCP keys → New key. Give your client the endpoint `https://papertrail.borant.eu/mcp` with the key in an `X-API-Key` header; clients that cannot set headers can use `https://papertrail.borant.eu/mcp/k/<your-key>` instead, where the URL *is* the credential and may end up in access logs — so use a separate key per client and revoke rather than share.

**What it reaches: exactly what you reach.** The key carries your identity, not an entitlement, and every call goes through the same permission check as the web pages. A workspace you are not a member of does not exist as far as your assistant is concerned, someone else's personal workspace included; revoking your membership revokes the key's reach with it.

**What it can do.** List your workspaces and their projects — filtered by status, by author, by how many days they have been silent, or by your own dots; read one project in full, with its notes, its whole submission chain, its links and its history; search; read the venue and people vocabularies before writing, so a venue is reused instead of respelled; create a project; add a note; move a status; open an attempt; record an outcome with the date on the letter; add and remove authors and links; and correct fields, venues and submission dates.

**Its search is lexical, not semantic**: substring matching over titles, summaries and notes. A miss means those words are not written there, never that nothing relevant exists — try synonyms, and try the other language.

**What it cannot do.** Delete a project (trash and destruction stay with a human looking at the board), manage members, or raise and clear dots — it reads your dots, you set them. It also addresses projects in their **home** workspace, so a project merely shared into a group is reached through the group that owns it.

Reads cost nothing, so ask freely. Writes land in a record your colleagues read: confirm them before they happen, the way you would before typing them yourself.

## 11. What PaperTrail does not do

**Deadlines have no interface** — until they do, a deadline lives in a note, and knowing that is better than discovering it. There are no per-venue latency statistics, no charts and no export in the app; the numbers are all in there, and getting them out is a query, not a button. An attempt's internal chronology is flat text, so individual revision rounds have no dates of their own. Search over ideas is lexical; the semantic pass over dormant ideas is a later phase. Nothing is imported from journals or ORCID, and **nothing notifies you** — dormancy is a filter you have to go and look at, which makes looking the human part of it. And PaperTrail decides nothing: it records where a paper is, never whether it should still be there.

## 12. Data protection

Stored: titles, summaries, author names, venues, dates, outcomes, notes, links, and one event per change with your name on it. Notes are free text and hold whatever you type into them — there is no field here designed for personal, health or otherwise special-category data, so do not make one out of a note. Author names and affiliations are personal data and are shared by design, because a bibliography is.

Who sees it: **every member of every workspace a project belongs to**, at their own role level, and `read` sees everything `write` sees. Sharing a project into a workspace grants its members access to it — that is what sharing means here, not a copy. Notes and history are visible to the whole workspace and cannot be edited or deleted from the interface.

Private to you, and nothing else is: your **flags** with their notes, and links ticked **only me**.

An MCP key is a second door onto exactly what you can already see, and content read through it reaches whichever model that client talks to. Make that judgement once, deliberately: a dedicated key per client, revoked when the project ends.

Deleting a project hides it in the workspace trash; a workspace admin destroying it from there takes its notes, attempts and history with it, permanently, and that is the only irreversible action in the tool. Authentication comes from Borant ID, and authorization stays in PaperTrail — the gate says who you are, membership says what you may touch.

## 13. Good practices

- **Open the attempt on the day the paper goes out.** Everything the tool can tell you about time is a subtraction of two dates; a venue and a date typed in three months later are a guess with a timestamp.
- **Type the date on the letter**, not the date you got round to recording it. The default is today, and today is almost always wrong.
- **Pick venues from the autocomplete.** One journal spelled two ways answers "how long does this venue take" twice, each time wrongly, and no amount of later analysis repairs it.
- **Move the card when you read the decision.** Declared status is a declaration, and the mismatch flag exists because declarations drift. Clear a mismatch the day it appears, while you still know which of the two is wrong.
- **Trust the submissions over the Journal field** whenever the two disagree about where a paper is.
- **The notes are the point.** The submission row says a paper was rejected; the note says why, and what the editor actually wanted. A year later that is worth more than the row.
- **Let the dot mean this week.** On twenty cards it means nothing.
- **Open the dormant filter once a month.** What gets forgotten is not what you are working on — it is what you stopped working on without ever deciding to.
- **Write the idea into your personal workspace now**, and share it into the group when it becomes the group's. Deciding whose it is later costs nothing; not writing it down costs the idea.
