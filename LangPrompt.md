
# LangPrompt

A small LangChain project that **learns a library of prompts** and, when you
plug in a new prompt, finds and prints the **most relevant** prompt from the
library using semantic (embedding-based) similarity.

## How it works

1. Prompts live in `prompts/`. Two formats are supported:
   - A **numbered file** (e.g. `prompts.txt`) where each prompt begins with a
     line like `1:` and runs until the next `2:` marker. Each entry becomes its
     own prompt (`Prompt 1`, `Prompt 2`, ...).
   - A standalone `.md`/`.txt` file with optional `--- ... ---` front matter,
     treated as a single prompt.
2. Each prompt is embedded with an OpenAI embedding model through LangChain and
   stored in an in-memory vector store. Embeddings are cached in `.cache/` and
   only recomputed when the prompt files change.
3. Your new prompt (the "query") is embedded and compared against the library
   with cosine similarity. The top 5 closest matches are printed (descending).
4. Every new user query is automatically appended to `prompts/prompts.txt`
   with the next number, so all queries are stored in one file like a cache.
   Exact duplicates are skipped.
5. YAML config queries (flat `KEY: value` files) are normalized to `Use ...`
   lines for matching; the workflow keys are still cached in `prompts.txt`.

## Setup

```bash
cd LangPrompt
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### API key

The app looks for the OpenAI key in this order:

1. `OPENAI_API_KEY` environment variable
2. a local `.env` file (copy `.env.example` to `.env`)
3. `../SYMFLUENCE/apikey` (already present in this workspace)

## Usage

```bash
# Interactive mode (type prompts, get the closest match):
python prompt_finder.py

# One-shot text query:
python prompt_finder.py -q "run summa preprocessing for bow river"

# YAML config file as query:
python prompt_finder.py -f prompts/example_config.yaml

# Config with intent and diff against a base template:
python prompt_finder.py -f my_config.yaml --base prompts/example_config.yaml --intent "change time period"

# Force re-embedding (e.g. after you change the embedding model):
python prompt_finder.py --rebuild
```

In interactive mode:
- `:k N` changes how many matches are shown
- `:file PATH` loads a YAML config file as the query
- `:intent TEXT` sets intent for the next `:file` query
- `:q` quits

## Adding your own prompts

Either add to the numbered file `prompts/prompts.txt`:

```
18:
Your full prompt text goes here. It can span
multiple lines and include blank lines until the
next numbered marker.

19:
The next prompt...
```

...or drop a separate `.md`/`.txt` file into `prompts/` with optional front
matter:

```markdown
---
title: Short human-friendly name
tags: comma, separated, keywords
---
Your full prompt text goes here...
```

The next run automatically detects the change and re-embeds.
