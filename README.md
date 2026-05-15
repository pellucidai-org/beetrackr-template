# beetrackr-template

[Copier](https://copier.readthedocs.io/) template for **web-scraping projects**.

A new project generated from this template comes pre-wired with:

| Layer       | Library                                          |
| ----------- | ------------------------------------------------ |
| HTTP        | [`httpx`](https://www.python-httpx.org/) (async) |
| Parsing     | [`beautifulsoup4`](https://www.crummy.com/software/BeautifulSoup/) + `lxml` |
| Browser     | [`playwright`](https://playwright.dev/python/)   |
| Crawler     | [`scrapy`](https://scrapy.org/) + [`scrapy-playwright`](https://github.com/scrapy-plugins/scrapy-playwright) |
| CLI         | [`typer`](https://typer.tiangolo.com/) + `rich`  |
| API         | [`fastapi`](https://fastapi.tiangolo.com/) + `uvicorn` |
| Settings    | [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) layered over `.env` + `config.yaml` |
| Logging     | [`structlog`](https://www.structlog.org/)        |

## Usage

Install Copier (one-time):

```bash
pipx install copier
# or: uv tool install copier
# or: pip install --user copier
```

Generate a new project:

```bash
copier copy gh:your-org/beetrackr-template ./my-scraper
# or from a local checkout:
copier copy /path/to/beetrackr-template ./my-scraper
```

You will be asked for:

- `project_name` — human-readable name
- `project_slug` — directory / distribution name (kebab-case)
- `package_name` — Python import name (snake_case)
- `project_description`, `author_name`, `author_email`, `python_version`, `license`
- `include_api` — scaffold the FastAPI service?
- `include_cli` — scaffold the Typer CLI?
- `include_scrapy` — scaffold Scrapy spiders?
- `include_playwright` — scaffold Playwright runner?

After generation:

```bash
cd my-scraper
pip install -e ".[dev]"     # or: uv sync
playwright install          # if include_playwright
cp .env.template .env       # then edit values
pytest                      # smoke tests should pass
```

## What the generated project looks like

```text
my-scraper/
├── .env.template                 # env-var skeleton
├── config.yaml                   # static scraper config (targets, selectors)
├── pyproject.toml
├── scrapy.cfg
├── src/my_scraper/
│   ├── settings.py               # pydantic-settings (env + yaml + json)
│   ├── logging.py                # structlog
│   ├── cli/main.py               # typer CLI: run, crawl, serve, config, targets
│   ├── api/
│   │   ├── app.py                # FastAPI app factory
│   │   └── routes/{health,scrape}.py
│   ├── scrapers/
│   │   ├── httpx_client.py       # async httpx + tenacity retries
│   │   ├── bs4_parser.py         # css-selector helpers
│   │   └── playwright_runner.py  # playwright runner
│   └── spiders/
│       ├── settings.py           # scrapy settings (reads pydantic config)
│       └── example.py            # example spider
└── tests/
    ├── test_settings.py
    └── test_bs4_parser.py
```

## Settings precedence (highest wins)

1. Constructor kwargs at runtime
2. Environment variables (and `.env`)
3. `config.yaml` (or JSON) referenced by `CONFIG_FILE`
4. Defaults defined on the pydantic models

Nested keys are separated by `__` in env vars, e.g.
`SCRAPER__USER_AGENT="my-bot/1.0"` → `settings.scraper.user_agent`.

## Updating a generated project

Copier remembers your answers in `.copier-answers.yml`. To pull template updates
into an existing project:

```bash
cd my-scraper
copier update
```

## Development of the template itself

```bash
# preview generation without writing
copier copy --pretend . /tmp/preview

# generate to a sandbox dir with defaults
copier copy --defaults --force . /tmp/sandbox

# run tests inside the generated project
cd /tmp/sandbox && pip install -e ".[dev]" && pytest
```

## License

MIT
