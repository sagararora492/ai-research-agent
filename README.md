# GitHub Portfolio Monorepo

This repository is structured as a monorepo for multiple portfolio projects.
Each application lives in `apps/`, and shared libraries can be added to
`packages/` as the repo grows.

**[View the portfolio](https://sagararora492.github.io/data-engineer-portfolio/)** · [Fieldnotes project walkthrough](https://sagararora492.github.io/data-engineer-portfolio/projects/fieldnotes/)

## Layout

```text
.
├── apps/
│   └── ai-agentic-research-assistant/
├── packages/
├── docs/                         # GitHub Pages portfolio
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

## Portfolio website

The static website lives in `docs/`. GitHub Pages publishes it from the `main`
branch's `/docs` folder. There is no frontend build step or runtime dependency.

Preview locally with `python3 -m http.server 8000 --directory docs`, then open
`http://localhost:8000`. Add future project showcases under `docs/projects/` and
link them from `docs/index.html`. Use relative asset links so the site works under
the repository's GitHub Pages path.

The Fieldnotes sample is a recorded offline run using fictional example documents;
the Python application itself runs locally and is not hosted by GitHub Pages.

`tooling/github-profile/README.md` is the source copy for the public profile README
in `sagararora492/sagararora492`. Changes to that copy must also be published to
the profile repository.
