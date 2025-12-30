#!/usr/bin/env python3
"""
Generate an HTML page from a CSV of arXiv IDs.

CSV is expected to have at least the following columns:
    date, name, arXiv ID, comments

For each arXiv ID, the script queries the arXiv API to obtain
title, authors, and abstract, then writes an HTML file where
each entry is wrapped in <div> elements with CSS class names
so that styling can be added later.

Usage:
    python generate_arxiv_html.py input.csv output.html
"""

import argparse
import csv
import html
import json
import re
import os
import ssl
import time
from datetime import datetime
import zoneinfo
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ARXIV_API_URL = "http://export.arxiv.org/api/query"

ARXIV_ID_RE = re.compile(
    r"\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Za-z-]+)?/\d{7}",
    flags=re.IGNORECASE,
)

ARXIV_XML_NS = {"atom": "http://www.w3.org/2005/Atom"}


def normalize_arxiv_id(raw_arxiv_id):
    m = ARXIV_ID_RE.search(raw_arxiv_id)
    if not m:
        return
    return m.group(0).lower()


def load_url(url, check_prefix="<?xml"):
    context = ssl._create_unverified_context()
    for i in range(1, 11):
        try:
            feed = urllib.request.urlopen(url, timeout=20, context=context).read().decode("utf-8")
        except IOError:
            pass
        else:
            if (check_prefix and feed.startswith(check_prefix)) or (feed and not check_prefix):
                return feed
        time.sleep(i * 2)
    raise IOError("Not able to connect to " + url)


class ArxivEntry:
    def __init__(self, entry):
        self.entry = entry
        self._attr_cache = dict()

    def __getattr__(self, name):
        _ns = ARXIV_XML_NS
        if name not in self._attr_cache:
            if name == "authors":
                output = [author.findtext("atom:name", "", _ns) for author in self.entry.iterfind("atom:author", _ns)]
            elif name == "first_author":
                output = self.entry.find("atom:author", _ns).findtext("atom:name", "", _ns)
            elif name in ("key", "id"):
                output = normalize_arxiv_id(self.entry.findtext("atom:id", "", _ns))
            else:
                output = self.entry.findtext("atom:{}".format(name), None, _ns)

            if output is not None:
                self._attr_cache[name] = output

        return self._attr_cache[name]

    __getitem__ = __getattr__


class ArxivFetcher:
    def __init__(self, url):
        self.url = url
        self.xml = load_url(self.url)
        try:
            self.root = ET.fromstring(self.xml)
        except ET.ParseError as e:
            print("Something wrong with URL: {}".format(self.url))
            raise e

        first_entry = self.root.find("atom:entry", ARXIV_XML_NS)
        if first_entry is not None and first_entry.findtext("atom:title", "Error", ARXIV_XML_NS) == "Error":
            self.root.remove(first_entry)

        self._entries = None

    @property
    def entries(self):
        if self._entries is None:
            self._entries = [ArxivEntry(e) for e in self.root.findall("atom:entry", ARXIV_XML_NS)]
        return list(self._entries)

    def iterentries(self):
        for entry in self.entries:
            yield entry

    def getentries(self):
        return self.entries


def fetch_arxiv_metadata(arxiv_ids, existing_metadata=None):
    metadata = existing_metadata or {}
    arxiv_ids = list(set(arxiv_ids) - set(metadata.keys()))

    if not arxiv_ids:
        return metadata

    AUTHORS_LIMIT = 6
    BATCH_SIZE = 50

    for start in range(0, len(arxiv_ids), BATCH_SIZE):
        batch = arxiv_ids[start : (start + BATCH_SIZE)]
        params = urllib.parse.urlencode({"id_list": ",".join(batch), "max_results": BATCH_SIZE})
        arxiv_results = ArxivFetcher(f"{ARXIV_API_URL}?{params}")
        for entry in arxiv_results.entries:
            metadata[entry.id] = {
                "title": entry.title,
                "authors": entry.authors[:AUTHORS_LIMIT],
                "has_more_authors": len(entry.authors) > AUTHORS_LIMIT,
                "abstract": entry.summary,
            }

    return metadata


# CSV column names (adjust here if your CSV uses different headers)
DATE_FIELD = "Timestamp"
NAME_FIELD = "Name"
ARXIV_ID_FIELD = "arXiv URL or ID"
COMMENTS_FIELD = "Comments"
HIDE_FIELD = "Hide"


def read_csv(path):
    """Read the input CSV file and return a list of row dictionaries."""
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def process_csv_rows(rows):
    """Process CSV rows to filter out hidden entries and normalize arXiv IDs."""
    processed_rows = {}

    for i, row in enumerate(rows):
        if row.get(HIDE_FIELD, "").strip().lower() == "true":
            continue
        arxiv_id = normalize_arxiv_id(row.get(ARXIV_ID_FIELD, ""))
        if not arxiv_id:
            continue

        name = row.get(NAME_FIELD, "").strip()
        date = "/".join(row.get(DATE_FIELD, "").strip().split("/")[:2])
        comments = row.get(COMMENTS_FIELD, "").strip()
        named_comment = (name, date, comments)

        if arxiv_id in processed_rows:
            existing_entry = processed_rows[arxiv_id]
            existing_entry["index"] = i
            existing_entry["date"] = date
            existing_entry["comments"].append(named_comment)
        else:
            processed_rows[arxiv_id] = {
                "arxiv_id": arxiv_id,
                "index": i,
                "date": date,
                "comments": [named_comment],
            }

    return sorted(processed_rows.values(), key=lambda x: x["index"], reverse=True)


def str2html(s):
    return "<br>".join(html.escape(line, quote=True) for line in s.splitlines())


def build_html(rows, metadata_by_id, template):
    """Build the HTML string for all rows using the provided metadata."""

    parts = []
    for row in rows:
        arxiv_id = row["arxiv_id"]
        meta = metadata_by_id.get(arxiv_id, {})

        parts.append('      <div class="t1 entry">')

        parts.append('        <div class="t2 entry-links">')
        parts.append(
            '          <div class="t3 entry-id"><a href="{abs_url}">{id}</a></div><div class="t3">[<a href="{pdf_url}">pdf</a>][<a href="{html_url}">html</a>]</div>'.format(
                id=arxiv_id,
                abs_url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                html_url=f"https://arxiv.org/html/{arxiv_id}",
            )
        )
        parts.append("        </div>")  # entry-links

        parts.append('        <div class="t2 entry-paper">')

        parts.append(f'          <div class="t3 entry-title">{str2html(meta.get("title", ""))}</div>')

        parts.append(
            '          <div class="t3 entry-authors">{authors}{more}</div>'.format(
                authors=str2html(", ".join(meta.get("authors", []))),
                more=(" et al." if meta.get("has_more_authors") else ""),
            )
        )

        parts.append("        </div>")  # entry-paper

        parts.append(
            f'        <div class="t2 entry-control"><a class="t3" href="javascript:toggle(\'abs-{row["index"]}\')">📖</a><a class="t3" href="javascript:toggle(\'cm-{row["index"]}\')">💬</a></div>'
        )

        parts.append(f'        <div class="t2 entry-abstract hide" id="abs-{row["index"]}">{str2html(meta.get("abstract", ""))}</div>')

        parts.append('        <div class="t2 entry-comments-all" id="cm-{}">'.format(row["index"]))
        for name, date, comments in row["comments"]:
            comments_formatted = (": " + str2html(comments)) if comments else ""
            parts.append(f'          <div class="t3 entry-comments"><b>{str2html(name)}</b> ({str2html(date)}){comments_formatted}</div>')
        parts.append("        </div>")  # entry-comments-all

        parts.append("      </div>")  # entry

    now = datetime.now(zoneinfo.ZoneInfo("US/Mountain")).strftime("%m/%d/%Y %H:%M:%S")
    entries = "\n".join(parts)

    return template.replace("<!-- TIME -->", now).replace("<!-- ENTRIES -->", entries)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate an HTML page from a CSV of arXiv IDs.")
    parser.add_argument("input_csv", help="Path to input CSV file.")
    parser.add_argument("template_html", help="Path to HTML template file.")
    parser.add_argument("output_html", help="Path to output HTML file.")
    parser.add_argument("--cache", help="Path to cache file.")
    args = parser.parse_args(argv)

    rows = process_csv_rows(read_csv(args.input_csv))
    arxiv_ids = [row["arxiv_id"] for row in rows]

    metadata_by_id = None
    if arxiv_ids:
        if args.cache and os.path.exists(args.cache):
            with open(args.cache, "r") as f:
                metadata_by_id = json.load(f)

        metadata_by_id = fetch_arxiv_metadata(arxiv_ids, metadata_by_id)

        if args.cache:
            with open(args.cache, "w") as f:
                json.dump(metadata_by_id, f)

    with open(args.template_html, "r") as f:
        template = f.read()

    html_text = build_html(rows, metadata_by_id, template)

    with open(args.output_html, "w") as f:
        f.write(html_text)

    return


if __name__ == "__main__":
    main()
