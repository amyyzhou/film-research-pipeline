# Film Research Pipeline

A multi-agent CLI tool that automates documentary film research. Given a topic or concept, it generates targeted search queries, fans out across four source categories in parallel, and synthesizes a production-ready research brief.

```
Planner (Claude) → Research agents (Exa / Claude web search) → Curator (Claude) → Brief
                                                                                  └→ Notion (optional)
```

## Features

- **Parallel research** across footage, editorial, academic, and B-roll sources
- **Dual search backends** — Exa neural search (preferred) or Claude web search fallback
- **Structured brief** with narrative angles, source notes, expert voices, and visual strategy
- **Notion export** — automatically creates a child page with linked sources
- **Markdown output** — save the brief locally with `--output`

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in your keys in .env
```

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `EXA_API_KEY` | No | Exa neural search (recommended for footage) |
| `NOTION_TOKEN` | No | Notion integration token |
| `NOTION_PAGE_ID` | No | Parent Notion page to write briefs into |

## Usage

```bash
# Interactive prompt
python film_research.py

# Pass concept directly
python film_research.py "the opioid crisis in rural Appalachia"

# Save brief to markdown
python film_research.py "factory farming and climate" --output brief.md
```

### Example output (truncated)

```
────────────────────────────────────────────────────
  FILM RESEARCH PIPELINE  ·  Multi-agent · Exa + Claude
────────────────────────────────────────────────────

[→] Stage 1: Planner — generating search queries  [running]

  Footage & Video:
    · "factory farming documentary footage archive"
    · "CAFO aerial footage climate impact"
    ...

[✓] Stage 2: Research agents — sources collected

  Footage & Video (5 found):
    1. Food, Inc. — Director's Cut (Magnolia Pictures)
       https://vimeo.com/...
       Behind-the-scenes look at industrial food production...
  ...

[✓] Stage 3: Curator — brief ready
────────────────────────────────────────────────────
## Core Narrative Threads
...
```

## How it works

1. **Planner** — Claude generates domain-specific search queries (video, editorial, research, B-roll) tailored to documentary production needs.
2. **Research agents** — queries fan out concurrently; each hits Exa's neural search filtered to relevant domains, or falls back to Claude's built-in web search tool.
3. **Curator** — Claude reads all collected sources and writes a structured brief: narrative angles, footage recommendations, expert voices, data anchors, and visual language strategy.
4. **Notion push** (optional) — the brief and linked sources are posted as a formatted child page.

## Source categories

| Category | Domains searched |
|---|---|
| Footage & Video | YouTube, Vimeo, Archive.org, Dailymotion |
| Editorial & Journalism | The Atlantic, NYT, The Guardian, Wired, Vox… |
| Academic Research | PubMed, arXiv, JSTOR, SSRN… |
| B-roll & Visual Reference | Unsplash, Getty, Pexels, Flickr… |
