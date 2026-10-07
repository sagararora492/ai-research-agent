# GitHub Portfolio Monorepo

This repository is structured as a monorepo for multiple portfolio projects.
Each application lives in `apps/`, and shared libraries can be added to
`packages/` as the repo grows.

## Layout

```text
.
├── apps/
│   └── ai-agentic-research-assistant/
├── packages/
├── tooling/
└── README.md
```

## Current Projects

- [Fieldnotes · Agentic Research Assistant](apps/ai-agentic-research-assistant/README.md): a local web studio and Python CLI for document/web research, optional model synthesis, validated citations, and saved evidence.

## Monorepo Conventions

- Put deployable apps in `apps/<project-name>/`
- Put reusable shared libraries in `packages/<package-name>/`
- Put repo-level scripts, templates, and automation in `tooling/`
- Keep each app responsible for its own package metadata, tests, and README
