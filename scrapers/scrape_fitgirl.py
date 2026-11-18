#!/usr/bin/env python3
"""Search FitGirl Repacks and download a selected torrent attachment."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://fitgirl-repacks.site/"
USER_AGENT = "fitgirl-search-title-scraper/1.1"
RESULT_LIMIT = 10


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str


class SearchResultsParser(HTMLParser):
    """Extract the first-page post titles and their URLs."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._title_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "h1" and self._has_class(attributes.get("class"), "entry-title"):
            self._in_title = True
            self._title_parts = []
            self._title_url = None
        elif tag == "a" and self._in_title and self._title_url is None:
            href = attributes.get("href")
            if href:
                self._title_url = urljoin(BASE_URL, href)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._in_title:
            title = " ".join("".join(self._title_parts).split())
            if title and self._title_url:
                self.results.append(SearchResult(title, self._title_url))
            self._in_title = False
            self._title_parts = []
            self._title_url = None

    @staticmethod
    def _has_class(value: str | None, expected: str) -> bool:
        return expected in (value or "").split()


class TorrentLinkParser(HTMLParser):
    """Find the .torrent file link on a repack page."""

    def __init__(self) -> None:
        super().__init__()
        self.torrent_url: str | None = None
        self._capture_link = False
        self._text_parts: list[str] = []
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._capture_link = True
            self._text_parts = []
            self._href = dict(attrs).get("href")

    def handle_data(self, data: str) -> None:
        if self._capture_link:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_link:
            text = " ".join("".join(self._text_parts).split()).lower()
            if text == ".torrent file only" and self._href:
                self.torrent_url = self._href
            self._capture_link = False
            self._text_parts = []
            self._href = None


def fetch_page(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def search(query: str, timeout: int) -> list[SearchResult]:
    url = f"{BASE_URL}?s={quote_plus(query)}"
    parser = SearchResultsParser()
    parser.feed(fetch_page(url, timeout))
    return parser.results[:RESULT_LIMIT]


def find_torrent_url(result: SearchResult, timeout: int) -> str:
    parser = TorrentLinkParser()
    parser.feed(fetch_page(result.url, timeout))
    if not parser.torrent_url:
        raise RuntimeError(
            f'Could not find ".torrent file only" on {result.url}'
        )
    return urljoin(result.url, parser.torrent_url)


def download_attachment(torrent_page_url: str, output_dir: Path, timeout: int) -> Path:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "The final download step requires Playwright. "
            "Install it with: python -m pip install playwright; "
            "then run: python -m playwright install chromium"
        ) from error

    output_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(accept_downloads=True)
            page.goto(torrent_page_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            with page.expect_download(timeout=timeout * 1000) as download_info:
                page.get_by_role("link", name="Download attachment").click()
            download = download_info.value
            target = output_dir / (download.suggested_filename or "download.torrent")
            download.save_as(str(target))
            return target
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                'Timed out waiting for the "Download attachment" link or download.'
            ) from error
        finally:
            browser.close()


def choose_result(results: list[SearchResult]) -> SearchResult:
    print("\nTop search results:\n")
    for index, result in enumerate(results, start=1):
        print(f"{index}. {result.title}")

    while True:
        selection = input(f"\nSelect a result (1-{len(results)}): ").strip()
        try:
            index = int(selection)
        except ValueError:
            print("Please enter a number.")
            continue
        if 1 <= index <= len(results):
            return results[index - 1]
        print(f"Please enter a number from 1 to {len(results)}.")


def main() -> int:
    argument_parser = argparse.ArgumentParser(
        description="Select a FitGirl Repacks result and download its torrent attachment."
    )
    argument_parser.add_argument(
        "query", nargs="?", help="search query; if omitted, the script prompts for one"
    )
    argument_parser.add_argument(
        "--timeout", type=int, default=30, help="HTTP/browser timeout in seconds"
    )
    argument_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="directory for the downloaded attachment (default: script directory)",
    )
    args = argument_parser.parse_args()

    query = (args.query or input("Search FitGirl Repacks for: ")).strip()
    if not query:
        argument_parser.error("a non-empty search query is required")
    if args.timeout < 1:
        argument_parser.error("--timeout must be at least 1")

    try:
        results = search(query, args.timeout)
        if not results:
            print(f"No results found for {query!r}.")
            return 0
        selected = choose_result(results)
        torrent_url = find_torrent_url(selected, args.timeout)
        print(f"\nOpening torrent page: {torrent_url}")
        downloaded_path = download_attachment(
            torrent_url, args.output_dir, args.timeout
        )
    except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Downloaded attachment to: {downloaded_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
