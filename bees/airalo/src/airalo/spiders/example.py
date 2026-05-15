"""Example Scrapy spider.

Run with::

    scrapy crawl example -O output.jsonl

Or via the project CLI::

    airalo crawl example
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import scrapy

from airalo.settings import get_settings


class ExampleSpider(scrapy.Spider):
    name = "example"

    def start_requests(self) -> Iterable[scrapy.Request]:
        settings = get_settings()
        target = settings.get_target("example")
        urls = target.start_urls if target else ["https://example.com/"]
        use_pw = bool(target and target.use_playwright)

        for url in urls:
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={"playwright": use_pw},
            )

    def parse(self, response: scrapy.http.Response) -> Iterable[dict[str, Any]]:
        yield {
            "url": response.url,
            "title": response.css("h1::text").get() or response.css("title::text").get(),
            "links": response.css("a::attr(href)").getall()[:50],
        }
