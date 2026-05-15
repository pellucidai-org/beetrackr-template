# Beets

Bee Travel eSIM scrapers — **Airalo** and **Vodafone Travel** in one project.

## Providers

| Provider | Command | Backend |
|----------|---------|---------|
| Airalo | `beets scrape -p airalo` | httpx + BeautifulSoup (`/all-esim` + country pages) |
| Vodafone Travel | `beets scrape -p vodafone` | Playwright + JSON-LD (`/our-destinations`) |

Generic config-driven targets use `beets run <target>` (httpx or playwright per `config.yaml`).

## Quick start

```bash
uv sync --extra dev
beets db init          # when storage.backend is sql
beets scrape -p airalo --limit 5
beets scrape -p vodafone --limit 5
beets serve            # FastAPI + dashboard on :8000
```

## Layout

```
bees/beets/
├── config.yaml          # targets: airalo, vodafone, example
├── src/beets/           # package (CLI, API, scrapers, storage)
└── tests/
```

Copier answers for regenerating: `beets-answers.yml` at the repo root.
