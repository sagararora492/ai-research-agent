# Fieldnotes · Agentic Research Assistant

A research assistant with a Python CLI and a local web studio. It plans evidence
needs, searches documents or the web, ranks and deduplicates sources, produces a
cited brief, and saves the evidence alongside the report. No runtime dependencies
are required beyond Python 3.12+.

**[Project walkthrough and sample output](https://sagararora492.github.io/projects/fieldnotes/)** · [Portfolio](https://sagararora492.github.io/)

## Start the web app

```bash
git clone https://github.com/sagararora492/ai-research-agent.git
cd ai-research-agent
PYTHONPATH=src python3 -m agentic_research_assistant.web
```

Open **http://127.0.0.1:8765**. Click **Try the sample research question**, then
**Start research**. Sample documents are fictional and clearly labelled. The
web app supports document import, live search, optional OpenAI synthesis,
source inspection, and Markdown copy/download. It only listens on localhost;
it is intended for a single user's local workspace, not public hosting.

Use `--port 9000` or `--storage-root /path/to/sessions` to override defaults.

## Install the command-line tools

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
research-assistant-web
```

Alternatively, every command runs without installation using `PYTHONPATH=src
python3 -m agentic_research_assistant.cli` or `.web`.

## Research modes

### Offline document research — no keys or network

```bash
research-assistant "How should we evaluate a research assistant?" \
  --provider local --documents examples/documents.json
```

Import a JSON array with 1–100 documents:

```json
[
  {
    "title": "Team interview notes",
    "content": "The actual document text to research...",
    "url": "https://example.com/optional-public-source"
  }
]
```

`title` and `content` are required; `url` is optional and must be HTTP(S).
Maximum title length: 500 characters; content: 100,000 characters per document.
The web request limit is 2 MB. Imports contain text, not local file paths or URLs
to fetch. Lexical ranking retrieves matching documents; an unrelated corpus may
produce no evidence. JSON is the supported import format; PDF parsing is not included.

### Live web research

Set `TAVILY_API_KEY` in the shell environment before starting the CLI or server:

```bash
export TAVILY_API_KEY='your-key'
research-assistant "How are teams evaluating enterprise search?" --provider tavily
```

The [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
returns results and extracted source text. If only a snippet is available, the
source is explicitly marked `snippet`. The app does not directly crawl result
URLs. Ranking scores indicate relevance, not source credibility.

### Optional model synthesis

```bash
export OPENAI_API_KEY='your-key'
export OPENAI_MODEL='your-accessible-structured-output-model-id'
research-assistant "How should we evaluate a research assistant?" \
  --provider local --documents examples/documents.json --synthesis openai
```

A model ID is intentionally explicit; choose one your account can use with the
[Responses API's structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
`--model` overrides `OPENAI_MODEL`. Source excerpts (up to the first 6,000 characters
per source) and the research question are
sent to OpenAI only when this mode is selected; API responses use `store: false`.
Keys are read from environment variables, never from the browser or saved session.
`.env` files are **not** loaded automatically.

Source text is treated as untrusted input. Synthesis must return one finding per
task, source IDs from the collected inventory, and exact quoted passages. Invalid
citations, refused or incomplete output, and provider errors trigger an explicit
warning and a fallback to the extractive findings. Uncited model claims are replaced
with the original evidence-based task result.

**Citation validation proves that the quoted passage exists in the collected
text. It does not prove that the source is true or that the claim follows from it.**
Human review is still needed for source authority, interpretation, and conflicting evidence.

### Planning only

```bash
research-assistant "What evidence would help us choose a search platform?"
```

The default mode creates a plan and seeded evidence targets. It makes no supported
findings and explicitly says that no evidence has been collected.

## CLI options

| Option | Default | Purpose |
| --- | --- | --- |
| `--provider plan\|local\|tavily` | `plan` | Evidence collection mode |
| `--documents PATH` | none | JSON corpus for local research |
| `--synthesis extractive\|openai` | `extractive` | Excerpts or model-written findings |
| `--model ID` | `OPENAI_MODEL` | Model used for synthesis |
| `--audience TEXT` | product and engineering stakeholders | Intended reader |
| `--outcome TEXT` | a decision-ready research brief | Research objective |
| `--max-sources N` | `3` | Results per task, 1–10 |
| `--max-searches N` | `6` | Search-call budget, minimum 3 (standard mode) |
| `--timeout SECONDS` | `30` | Per-request timeout, maximum 120 |
| `--storage-root PATH` | `./data/research_sessions` | Artifact directory |
| `--no-persist` | off | Collect and synthesize entirely in memory |
| `--format markdown\|json` | `markdown` | Machine-readable or human-readable output |

The researcher first searches all three tasks, then retries empty tasks with a
broader topic query if the budget allows. HTTP 429 and transient server/connection
failures receive at most two retries with backoff. Retries are additional HTTP
attempts; `--max-searches` counts logical search calls. Model synthesis uses one
logical request. Live modes can incur provider charges.

```bash
research-assistant "Research assistants" --provider local \
  --documents examples/documents.json --no-persist --format json > report.json
```

Reports go to stdout; saved-session notices and CLI errors go to stderr. Exit 0
means a report was produced (possibly with warnings); exit 1 means a configuration,
input, provider setup, or storage error; exit 130 means interrupted. Check the
report's warnings and collected source count before treating a run as successful research.

## Saved artifacts

Every persisted run gets a timestamp, bounded topic slug, and random session ID:

```text
data/research_sessions/<session-id>/
├── report.md        # brief, citations, gaps, and run warnings
├── sources.json     # deduplicated inventory, content, URLs, and metadata
├── session.json     # schema version, tasks, queries, findings, and paths
└── sources/*.md     # individual source text or planned collection templates
```

`session.json` is written last and marks a completed save. A disk failure may leave
an incomplete directory without a completed manifest. No-persist mode performs the
same research and validation without creating a session directory.

## Architecture

```text
CLI / local web UI
       ↓
ResearchOrchestrator
       ├─ Planner → three scoped evidence tasks
       ├─ Researcher → search → rank / deduplicate → bounded follow-up
       ├─ Synthesizer → extractive or OpenAI → citation validation
       └─ Collector + Storage → source artifacts, brief, session manifest
```

- `providers.py`: search protocol, local/Tavily adapters, bounded JSON transport.
- `researcher.py`: research budget, evidence extraction, and task/source associations.
- `synthesizer.py`: model integration, citation checks, and Markdown rendering.
- `config.py`: shared CLI/web construction; credentials stay server-side.
- `web.py` / `static/`: localhost HTTP API and accessible responsive interface.

A `SearchProvider` implements `search(query, limit) -> list[SearchResult]` and raises
`ProviderError` for recoverable search failures. Inject it into `Researcher`, then
into `ResearchOrchestrator`. The planner is deterministic; this is a bounded
research workflow, not an unconstrained autonomous browsing agent.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests use local corpora and mocked provider responses: no credentials, network,
or paid requests are needed. Coverage includes orchestration, citation rejection,
model refusal/fallback, search budgets/recovery, URL normalization, provider retries,
CLI JSON/errors, web input validation, and persistence. GitHub Actions runs the
suite and package smoke tests on Python 3.12 and 3.13.

## Configure a team with different models

Enable **Configure an agent team** in the web app and add the agents you need.
Each agent can select any locally configured model profile. There is no fixed
agent count, model count, or required distribution. Planner and synthesis models
are selected independently. Concurrency is a separate user-configurable limit;
large teams queue behind that limit rather than all running simultaneously.

Credentials and connection settings are local only. Start the server with a model
catalog containing profile names and model IDs (never key values):

```bash
PYTHONPATH=src python3 -m agentic_research_assistant.web --models-config examples/models.json
```

Edit that file to use any model IDs supported by your providers, and set API keys
in the server's shell environment. The browser receives only profile names,
provider names, and model IDs. It cannot change credential variables or endpoints.
Add profiles locally and restart the server to refresh the catalog.

The UI imports/exports agent assignments without provider connection settings.
Use exported assignments with the CLI's `--agent-config` and `--models-config`
options. **Use excerpts only** disables model calls for every role.

### CLI configuration

Start with [examples/agents-mixed.json](examples/agents-mixed.json), replace the
three `YOUR_*_MODEL_ID` placeholders, and configure provider keys in the server's
shell environment: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY`.
Then run:

```bash
research-assistant "How should we evaluate a research assistant?" \
  --provider local --documents examples/documents.json \
  --agent-config examples/agents-mixed.json
```

A complete offline ten-agent example also works without keys:

```bash
PYTHONPATH=src python3 -m agentic_research_assistant.cli "Research assistants" \
  --provider local --documents examples/documents.json \
  --agent-config examples/agents-offline.json --no-persist
```

The configuration has this shape (model IDs below are placeholders):

```json
{
  "models": {
    "fast": {"provider": "openai", "model": "YOUR_OPENAI_MODEL_ID"},
    "review": {"provider": "anthropic", "model": "YOUR_ANTHROPIC_MODEL_ID"},
    "broad": {"provider": "gemini", "model": "YOUR_GEMINI_MODEL_ID"}
  },
  "default_model": "fast",
  "planner_model": "broad",
  "synthesizer_model": "review",
  "max_concurrency": 3,
  "max_searches": 6,
  "on_error": "fallback",
  "research_agents": [
    {"id": "technical", "focus": "Technical feasibility", "model": "fast"},
    {"id": "risks", "focus": "Risks and contradictory evidence", "model": "review"},
    {"id": "market", "focus": "Alternatives and adoption", "model": "broad"}
  ]
}
```

Model assignments refer to profile names. Omitted assignments inherit
`default_model`; explicit `null` disables the model for that role. With no default,
omitted assignments use deterministic planning, extractive research, or passthrough
synthesis. The agent configuration owns all model selection: do not combine it with
`--model` or `--synthesis openai`.

### Provider connections

| Profile provider | API | Default credential environment variable |
| --- | --- | --- |
| `openai` | Responses with structured outputs | `OPENAI_API_KEY` |
| `anthropic` | Messages with structured outputs | `ANTHROPIC_API_KEY` |
| `gemini` | GenerateContent with JSON schema | `GEMINI_API_KEY` |
| `openai_compatible` | Chat Completions | `OPENAI_COMPATIBLE_API_KEY` |

Local profiles may override `api_key_env` to use separate accounts. They accept
`max_output_tokens` (256–32,000, default 6,000). Keys themselves must never appear
in configuration files; unknown fields such as `api_key` are rejected.

For a local or third-party compatible server, add a profile like:

```json
{
  "provider": "openai_compatible",
  "model": "YOUR_SERVER_MODEL_ID",
  "base_url_env": "LOCAL_BASE_URL",
  "api_key_env": "LOCAL_API_KEY",
  "structured_output": "json_object",
  "max_output_tokens": 4000
}
```

Set `LOCAL_BASE_URL` to the server's API base URL, for example
`http://127.0.0.1:11434/v1`. The adapter appends `/chat/completions`. Localhost
endpoints may omit credentials; remote endpoints require HTTPS and an API key.
The endpoint URL is read from the server environment, not supplied directly in
browser requests. For servers supporting strict schemas, use the default
`structured_output: "json_schema"`; `json_object` passes the schema in the prompt
and still applies the app's task, finding, and citation validators. Compatibility
depends on the server and model; unsupported formats produce a visible failure.

The integrations follow the official documentation for
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses),
[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[Gemini GenerateContent](https://ai.google.dev/api/generate-content), and
[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Select a model supporting the corresponding structured-output API. Model availability
and provider limits are account-specific; no model is silently substituted.

### Execution and limits

- Configure any positive number of research agents and concurrent workers. A model profile can
  be shared across any number of agents; each agent gets an independent client.
- Each agent receives its own focus/task, retrieves evidence, and invokes its
  assigned model to analyze that evidence. The optional model planner refines the
  evidence tasks; it cannot change agent/model assignments.
- The final synthesis sees the worker findings and collected evidence. With a
  `null` synthesis model, worker findings are retained directly.
- `max_searches` is a session-wide budget, split fairly before workers start.
  It defaults to twice the agent count, must be at least the agent count, and
  has no fixed upper limit. CLI `--max-searches` overrides it. Each worker currently performs
  one initial search and, if empty, at most one broader follow-up; unused budget
  is not spent automatically. Provider HTTP retries are additional attempts.
- The default `on_error: "fallback"` preserves collected excerpts when a model
  fails and records a warning. `"fail"` rejects the session on model/provider-output
  failure. Missing credentials and invalid configurations always fail before
  research begins. Search failures remain visible as evidence gaps and warnings.
- Traces distinguish model completion, excerpt-only execution, no evidence, and
  fallbacks. A no-evidence agent does not make a model call. Usage contains only
  token counts actually reported by the provider, not estimated costs or retry
  charges. Latency includes search and model work for research agents.
- Sources with identical URLs **and content** are deduplicated after workers
  complete. Different content from the same URL is retained to preserve quotes.
- `session.json` schema version 2 stores resolved configuration and `agent_runs`,
  including the original worker findings. API keys and endpoint values are not
  stored. JSON reports include these fields even with `--no-persist`.

The harness remains a bounded workflow: models analyze retrieved evidence rather
than choosing arbitrary tools or executing code. Adding more agents increases
search/model calls and can increase cost; concurrency controls parallelism, not
total spend. Live provider calls are opt-in through model assignments.
