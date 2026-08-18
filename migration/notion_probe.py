"""
Read-only reconnaissance of the Notion source before any import.

Answers one question: what would actually arrive if we migrated today?

Nothing is written anywhere — not to Notion, not to PaperTrail. The point is to
find out *before* dismantling the current system how much of it the API can
still see, given two known platform limits:

  1. Resolved comment threads are invisible to the API. Whatever was marked
     resolved cannot be retrieved by any tool, ours included.
  2. Inline comments hang off inner blocks, not the page, so asking for a
     page's comments misses them. This script walks one level of children to
     count them.

Page and database ids come from the export filenames — no lookup needed.

Usage:
    python migration/notion_probe.py            # full run over every page
    python migration/notion_probe.py --limit 10 # quick sample
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
THROTTLE = 0.35          # Notion allows ~3 req/s averaged; stay under it

EXPORT_DIR = (Path(__file__).resolve().parents[2]
              / "raw" / "ingest" / "notion-pipeline" / "Private & Shared")
PAGES_DIR = EXPORT_DIR / "Scatola delle idee"


def load_token() -> str:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("NOTION_TOKEN="):
                    token = line.split("=", 1)[1].strip()
    if not token:
        sys.exit("NOTION_TOKEN mancante (mettilo in papertrail/.env)")
    return token


TOKEN = load_token()


def call(path: str, params: str = "") -> dict | None:
    req = urllib.request.Request(f"{API}/{path}{params}")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        return {"_error": e.code, "_body": body}
    finally:
        time.sleep(THROTTLE)


def page_ids() -> list[tuple[str, str]]:
    """(page_id, title) from the export filenames, newest export wins."""
    out = []
    for f in sorted(PAGES_DIR.glob("*.md")):
        m = re.search(r"([0-9a-f]{32})\.md$", f.name)
        if m:
            title = f.name[: m.start()].strip()
            out.append((m.group(1), title))
    return out


def dashed(pid: str) -> str:
    return f"{pid[:8]}-{pid[8:12]}-{pid[12:16]}-{pid[16:20]}-{pid[20:]}"


def plain(rich) -> str:
    return "".join(t.get("plain_text", "") for t in (rich or []))


def user_directory() -> dict[str, str]:
    """
    id -> display name.

    Comments carry a *partial* user object (id only), even when the integration
    has "read user information": the name has to be resolved against the
    workspace directory, which /v1/users returns in full.
    """
    people, cursor = {}, None
    while True:
        params = "?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        data = call("users", params)
        if not data or "_error" in data:
            break
        for u in data.get("results", []):
            people[u["id"]] = u.get("name") or u.get("id", "")[:8]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return people


def resolve_user(uid: str, people: dict[str, str]) -> str:
    """
    Name for a user id, falling back to a direct lookup.

    /v1/users lists workspace *members* only. Someone who is a guest on the page
    — which is how Federico appears here — is absent from that list but resolves
    fine one id at a time. Without this fallback his 70 comments would import
    signed by a UUID.
    """
    if not uid:
        return "?"
    if uid not in people:
        u = call(f"users/{uid}")
        people[uid] = ((u or {}).get("name") or uid[:8]) if u and "_error" not in u else uid[:8]
    return people[uid]


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    pages = page_ids()
    if limit:
        pages = pages[:limit]
    people = user_directory()
    print(f"Pagine da sondare: {len(pages)} · "
          f"utenti nel workspace: {len(people)}\n")

    ok = 0
    errors = Counter()
    created = []
    comments_total = 0
    inline_total = 0
    pages_with_comments = 0
    authors = Counter()
    per_page = []

    for i, (pid, title) in enumerate(pages, 1):
        pdata = call(f"pages/{dashed(pid)}")
        if pdata is None or "_error" in pdata:
            errors[pdata.get("_error", "?") if pdata else "?"] += 1
            if errors.total() <= 3:
                print(f"  ! {title[:50]}: {pdata.get('_body', '')[:120]}")
            continue
        ok += 1
        created.append((pdata.get("created_time"), pdata.get("last_edited_time"),
                        title))

        cdata = call("comments", f"?block_id={dashed(pid)}&page_size=100")
        n_page = 0
        if cdata and "_error" not in cdata:
            for c in cdata.get("results", []):
                n_page += 1
                authors[resolve_user(c.get("created_by", {}).get("id"), people)] += 1

        # Inline comments live on child blocks, so page-level retrieval misses
        # them. One level down is enough to size the problem.
        n_inline = 0
        bdata = call(f"blocks/{dashed(pid)}/children", "?page_size=100")
        if bdata and "_error" not in bdata:
            for b in bdata.get("results", []):
                if not b.get("has_children") and not b.get("id"):
                    continue
                # Only blocks that can carry a discussion are worth asking about.
                if b.get("type") in ("paragraph", "heading_1", "heading_2",
                                     "heading_3", "bulleted_list_item",
                                     "numbered_list_item", "to_do", "quote",
                                     "callout"):
                    ic = call("comments", f"?block_id={b['id']}&page_size=100")
                    if ic and "_error" not in ic:
                        for c in ic.get("results", []):
                            n_inline += 1
                            authors[resolve_user(
                                c.get("created_by", {}).get("id"), people)] += 1

        comments_total += n_page
        inline_total += n_inline
        if n_page or n_inline:
            pages_with_comments += 1
            per_page.append((n_page + n_inline, title))

        if i % 10 == 0 or i == len(pages):
            print(f"  … {i}/{len(pages)}  ok={ok}  commenti={comments_total + inline_total}")

    print("\n" + "=" * 64)
    print(f"Pagine leggibili           : {ok}/{len(pages)}")
    if errors:
        print(f"Errori                     : {dict(errors)}")
    print(f"Pagine con commenti visibili: {pages_with_comments}")
    print(f"Commenti a livello pagina   : {comments_total}")
    print(f"Commenti inline             : {inline_total}")
    print(f"TOTALE recuperabile         : {comments_total + inline_total}")

    if authors:
        print("\nAutori dei commenti:")
        for who, n in authors.most_common():
            print(f"  {n:4d}  {who}")

    if per_page:
        print("\nPagine più commentate:")
        for n, title in sorted(per_page, reverse=True)[:12]:
            print(f"  {n:4d}  {title[:60]}")

    ts = [c for c, _, _ in created if c]
    if ts:
        print(f"\nTimestamp: {len(ts)}/{ok} pagine con created_time")
        print(f"  più vecchia: {min(ts)}")
        print(f"  più recente: {max(ts)}")

    Path(__file__).parent.joinpath("probe_report.json").write_text(
        json.dumps({"ok": ok, "total": len(pages), "errors": dict(errors),
                    "comments_page": comments_total, "comments_inline": inline_total,
                    "authors": dict(authors),
                    "per_page": [{"n": n, "title": t} for n, t in
                                 sorted(per_page, reverse=True)],
                    "created": [{"created": c, "edited": e, "title": t}
                                for c, e, t in created]},
                   indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nDettaglio salvato in migration/probe_report.json")


if __name__ == "__main__":
    main()
