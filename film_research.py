#!/usr/bin/env python3
"""
Film Research Pipeline
Multi-agent: Planner → Exa Research → Curator → (Notion)
Usage: python film_research.py [concept] [--output brief.md]
"""

import os
import re
import json
import sys
import asyncio
import aiohttp
import argparse
from datetime import date

# ── Config ─────────────────────────────────────────────────────────────────────
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
EXA_KEY        = os.environ.get("EXA_API_KEY", "")
NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
EXA_URL       = "https://api.exa.ai/search"
NOTION_URL    = "https://api.notion.com/v1"
MODEL         = "claude-sonnet-4-6"

CATEGORY_DOMAINS = {
    "video":      ["youtube.com", "vimeo.com", "archive.org", "dailymotion.com"],
    "editorial":  ["theatlantic.com", "newyorker.com", "nytimes.com", "wired.com",
                   "theguardian.com", "vox.com", "axios.com", "nymag.com"],
    "research":   ["ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "arxiv.org",
                   "jstor.org", "ssrn.com", "scholar.google.com"],
    "broll":      ["unsplash.com", "pexels.com", "gettyimages.com", "shutterstock.com",
                   "reddit.com", "flickr.com"],
}

CATEGORY_LABELS = {
    "video":     "Footage & Video",
    "editorial": "Editorial & Journalism",
    "research":  "Academic Research",
    "broll":     "B-roll & Visual Reference",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
def print_header(text):
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"  {text}")
    print(bar)

def print_step(n, label, status=""):
    icon = "✓" if status == "done" else "→" if status == "running" else "○"
    suffix = f"  [{status}]" if status else ""
    print(f"\n[{icon}] Stage {n}: {label}{suffix}")

def print_result(r, idx):
    title   = r.get("title") or r.get("url", "")
    url     = r.get("url", "")
    summary = r.get("summary", "")
    if isinstance(summary, dict):
        summary = summary.get("summary", "")
    print(f"\n  {idx}. {title}")
    if url:     print(f"     {url}")
    if summary: print(f"     {summary[:180]}{'...' if len(summary) > 180 else ''}")

def _extract_json(raw, opener="{"):
    """Strip markdown fences and extract the first JSON object/array."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    idx = clean.find(opener)
    if idx != -1:
        clean = clean[idx:]
    return json.loads(clean)

def _save_markdown(concept, brief, all_results, path):
    lines = [
        f"# Research Brief: {concept}",
        f"*Generated {date.today().isoformat()}*\n",
        brief,
        "\n---\n\n## Sources\n",
    ]
    for cat, results in all_results.items():
        if not results:
            continue
        lines.append(f"### {CATEGORY_LABELS.get(cat, cat)}\n")
        for r in results:
            title   = r.get("title", r.get("url", ""))
            url     = r.get("url", "")
            summary = str(r.get("summary", ""))[:200]
            link    = f"[{title}]({url})" if url else title
            lines.append(f"- {link}: {summary}")
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n  Brief saved → {path}")

# ── API calls ──────────────────────────────────────────────────────────────────
async def call_claude(session, messages, system, *, max_tokens=1024, tools=None):
    body = {
        "model":      MODEL,
        "max_tokens": max_tokens,
        "system":     system,
        "messages":   messages,
    }
    if tools:
        body["tools"] = tools

    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }
    async with session.post(ANTHROPIC_URL, json=body, headers=headers) as resp:
        data = await resp.json()
        if resp.status != 200:
            raise RuntimeError(data.get("error", {}).get("message", f"HTTP {resp.status}"))
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return " ".join(text_blocks)


async def exa_search(session, query, category):
    body = {
        "query":          query,
        "numResults":     4,
        "useAutoprompt":  True,
        "includeDomains": CATEGORY_DOMAINS.get(category, []),
        "contents":       {"summary": {"query": query}},
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key":    EXA_KEY,
    }
    async with session.post(EXA_URL, json=body, headers=headers) as resp:
        data = await resp.json()
        if resp.status != 200:
            raise RuntimeError(f"Exa HTTP {resp.status}: {data}")
        return data.get("results", [])


async def claude_search_fallback(session, query, category):
    """Use Claude web_search tool when no Exa key is available."""
    cat_hint = {
        "video":     "YouTube, Vimeo, or video archive footage",
        "editorial": "long-form editorial articles or journalism",
        "research":  "academic research papers or studies",
        "broll":     "visual reference images or B-roll footage",
    }.get(category, "relevant sources")

    prompt = (
        f"Search for: {query}\n\n"
        f"Find {cat_hint}. Return a JSON array (no markdown) of up to 3 results, "
        f"each with: title, url, summary (1-2 sentences). Only return the JSON array."
    )
    body = {
        "model":      MODEL,
        "max_tokens": 1024,
        "system":     "You are a research assistant. Search the web and return results as a clean JSON array. No preamble, no markdown fences.",
        "messages":   [{"role": "user", "content": prompt}],
        "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
    }
    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }
    async with session.post(ANTHROPIC_URL, json=body, headers=headers) as resp:
        data = await resp.json()
        if resp.status != 200:
            raise RuntimeError(data.get("error", {}).get("message", f"HTTP {resp.status}"))
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return _extract_json(" ".join(text_blocks), opener="[")


# ── Notion ─────────────────────────────────────────────────────────────────────
def _notion_headers():
    return {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Content-Type":   "application/json",
        "Notion-Version": "2022-06-28",
    }

def _md_to_blocks(md_text):
    """Convert basic markdown to Notion block objects."""
    blocks = []
    for line in md_text.split("\n"):
        if line.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": line[4:]}}]}})
        elif line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]}})
        elif line.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]}})
        elif re.match(r"^[-*] ", line):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]}})
        elif line.strip() == "":
            blocks.append({"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": []}})
        else:
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            blocks.append({"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": clean}}]}})
    return blocks

async def push_to_notion(session, concept, brief, all_results):
    if not NOTION_TOKEN or not NOTION_PAGE_ID:
        print("\n  [skip] No Notion credentials — set NOTION_TOKEN and NOTION_PAGE_ID to enable.")
        return

    print("\n  Pushing to Notion...", end=" ", flush=True)
    title = f"Research Brief: {concept}  ·  {date.today().isoformat()}"

    source_blocks = []
    for cat, results in all_results.items():
        if not results:
            continue
        source_blocks.append({
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": CATEGORY_LABELS.get(cat, cat)}}]}
        })
        for r in results:
            t = r.get("title", r.get("url", ""))
            u = r.get("url", "")
            s = str(r.get("summary", ""))[:120]
            text_obj: dict = {"content": f"{t} — {s}" if s else t}
            if u:
                text_obj["link"] = {"url": u}
            source_blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": text_obj}]}
            })

    divider = {"object": "block", "type": "divider", "divider": {}}
    blocks = (
        [divider]
        + _md_to_blocks(brief)
        + [divider,
           {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Sources"}}]}}]
        + source_blocks
    )

    page_body = {
        "parent":     {"page_id": NOTION_PAGE_ID},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "children":   blocks[:100],
    }
    async with session.post(f"{NOTION_URL}/pages", headers=_notion_headers(), json=page_body) as resp:
        if resp.status != 200:
            body = await resp.json()
            raise RuntimeError(f"Notion {resp.status}: {body.get('message', body)}")
        new_page_id = (await resp.json())["id"]

    for i in range(100, len(blocks), 100):
        async with session.patch(
            f"{NOTION_URL}/blocks/{new_page_id}/children",
            headers=_notion_headers(),
            json={"children": blocks[i:i+100]},
        ) as resp:
            if resp.status not in (200, 204):
                body = await resp.json()
                raise RuntimeError(f"Notion {resp.status}: {body.get('message', body)}")

    url = f"https://notion.so/{new_page_id.replace('-', '')}"
    print(f"done\n  {url}")


# ── Pipeline stages ─────────────────────────────────────────────────────────────
async def stage_planner(session, concept):
    print_step(1, "Planner — generating search queries", "running")
    prompt = (
        f'Film concept: "{concept}"\n\n'
        "Generate a research plan as a JSON object (no markdown) with this exact structure:\n"
        '{\n'
        '  "video": ["query1","query2","query3"],\n'
        '  "editorial": ["query1","query2"],\n'
        '  "research": ["query1","query2"],\n'
        '  "broll": ["query1","query2"]\n'
        '}\n\n'
        "Make queries specific and useful for documentary filmmaking. Return ONLY the JSON."
    )
    system = (
        "You are a documentary film researcher. Generate targeted search queries "
        "for film research. Return only valid JSON, no markdown, no explanation."
    )
    raw     = await call_claude(session, [{"role": "user", "content": prompt}], system)
    queries = _extract_json(raw, opener="{")

    print_step(1, "Planner — search queries generated", "done")
    for cat, qs in queries.items():
        print(f"\n  {CATEGORY_LABELS.get(cat, cat)}:")
        for q in qs:
            print(f"    · {q}")
    return queries


async def search_one(session, query, category):
    """Search via Exa if key is present, else fall back to Claude web search."""
    try:
        if EXA_KEY:
            results = await exa_search(session, query, category)
            return [
                {
                    "title":   r.get("title") or r.get("url", ""),
                    "url":     r.get("url", ""),
                    "summary": (
                        r.get("summary") if isinstance(r.get("summary"), str)
                        else (r.get("summary") or {}).get("summary", "")
                        or r.get("text", "")[:200]
                    ),
                    "type": category,
                }
                for r in results
            ]
        else:
            results = await claude_search_fallback(session, query, category)
            return [{**r, "type": category} for r in results]
    except Exception as e:
        print(f"    [warn] Search failed for '{query}': {e}")
        return []


async def stage_research(session, queries):
    print_step(2, "Research agents — sourcing footage & references", "running")
    if not EXA_KEY:
        print("  (No Exa key — using Claude web search fallback)")

    tasks = [
        (cat, q, search_one(session, q, cat))
        for cat, qs in queries.items()
        for q in qs
    ]

    results_by_cat = {cat: [] for cat in queries}
    gathered = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)

    for (cat, q, _), result in zip(tasks, gathered):
        if isinstance(result, Exception):
            print(f"  [warn] {q}: {result}")
        else:
            results_by_cat[cat].extend(result)

    for cat in results_by_cat:
        seen, deduped = set(), []
        for r in results_by_cat[cat]:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                deduped.append(r)
        results_by_cat[cat] = deduped[:5]

    print_step(2, "Research agents — sources collected", "done")
    for cat, results in results_by_cat.items():
        if not results:
            continue
        print(f"\n  {CATEGORY_LABELS.get(cat, cat)} ({len(results)} found):")
        for i, r in enumerate(results, 1):
            print_result(r, i)

    return results_by_cat


async def stage_curator(session, concept, all_results):
    print_step(3, "Curator — synthesizing research brief", "running")

    digest_parts = []
    for cat, results in all_results.items():
        if not results:
            continue
        lines = [
            f"  - [{r.get('title', r.get('url',''))}]({r.get('url','')}): {str(r.get('summary',''))[:120]}"
            for r in results
        ]
        digest_parts.append(f"{cat.upper()} SOURCES:\n" + "\n".join(lines))
    digest = "\n\n".join(digest_parts)

    prompt = (
        f'Film concept: "{concept}"\n\n'
        f"Research gathered:\n{digest}\n\n"
        "Write a structured research brief for a documentary filmmaker. Include:\n"
        "1. Core narrative threads (2-3 key angles)\n"
        "2. Recommended footage sources with notes on how to use them\n"
        "3. Key expert/editorial voices to pursue\n"
        "4. Suggested academic/data anchors\n"
        "5. Visual language and B-roll strategy\n\n"
        "Be concrete, specific, and filmmaker-focused. When referencing any source, "
        "use markdown hyperlink format: [Title](url). Every source mentioned must be linked."
    )
    system = (
        "You are a senior documentary researcher and story producer. "
        "Write sharp, actionable research briefs that help filmmakers find their story."
    )
    brief = await call_claude(
        session,
        [{"role": "user", "content": prompt}],
        system,
        max_tokens=2048,
    )

    print_step(3, "Curator — brief ready", "done")
    print("\n" + "─" * 60)
    print(brief)
    print("─" * 60)

    return brief


# ── Main ────────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Film Research Pipeline — multi-agent documentary research tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  ANTHROPIC_API_KEY  (required)\n"
            "  EXA_API_KEY        optional — neural search; falls back to Claude web search\n"
            "  NOTION_TOKEN       optional — push brief to Notion\n"
            "  NOTION_PAGE_ID     optional — parent Notion page ID\n"
        ),
    )
    parser.add_argument("concept", nargs="*", help="Film concept or topic to research")
    parser.add_argument("--output", "-o", metavar="FILE", help="Save brief as a markdown file")
    return parser.parse_args()


async def main():
    args = parse_args()

    if not ANTHROPIC_KEY:
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    print_header("FILM RESEARCH PIPELINE  ·  Multi-agent · Exa + Claude")

    if EXA_KEY:
        print("  Exa key detected — using neural video/source search")
    else:
        print("  No EXA_API_KEY — falling back to Claude web search")
        print("  For best footage results: export EXA_API_KEY=exa-...")

    if args.concept:
        concept = " ".join(args.concept)
    else:
        print()
        concept = input("Film concept: ").strip()
        if not concept:
            print("No concept entered. Exiting.")
            sys.exit(0)

    print(f'\n  Researching: "{concept}"')

    connector = aiohttp.TCPConnector(limit=10)
    timeout   = aiohttp.ClientTimeout(total=120)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        queries     = await stage_planner(session, concept)
        all_results = await stage_research(session, queries)
        brief       = await stage_curator(session, concept, all_results)

        if args.output:
            _save_markdown(concept, brief, all_results, args.output)

        await push_to_notion(session, concept, brief, all_results)

    print("\nDone.\n")


if __name__ == "__main__":
    asyncio.run(main())
