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
            feed = urllib.request.urlopen(url, timeout=20, context=context).read().decode('utf-8')
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
                output = [
                    author.findtext("atom:name", "", _ns)
                    for author in self.entry.iterfind("atom:author", _ns)
                ]
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
        if (
            first_entry is not None
            and first_entry.findtext("atom:title", "Error", ARXIV_XML_NS) == "Error"
        ):
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
        batch = arxiv_ids[start:(start+BATCH_SIZE)]
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


def build_html(rows, metadata_by_id):
    """Build the HTML string for all rows using the provided metadata."""
    parts = []

    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('  <meta charset="utf-8">')
    parts.append('  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('  <link rel="preconnect" href="https://fonts.googleapis.com" />')
    parts.append('  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />')
    parts.append('  <meta name="creator" content="Yao-Yuan Mao">')
    parts.append('  <link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;700&display=swap" rel="stylesheet">')
    parts.append("  <title>Mao Astro Group Paper Discussion</title>")
    parts.append('  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/modern-normalize/3.0.1/modern-normalize.min.css" integrity="sha512-q6WgHqiHlKyOqslT/lgBgodhd03Wp4BEqKeW6nNtlOY4quzyG3VoQKFrieaCeSnuVseNKRGpGeDU3qPmabCANg==" crossorigin="anonymous" referrerpolicy="no-referrer" />')
    parts.append("""
  <style>
    html, body{
      font-family: 'Source Sans 3', sans-serif;
    }
    body {
      color: #222;
    }
    a:any-link {
      color: #08c;
      text-decoration: none;
    }
    .content {
      max-width: 1020px;
      margin: 0 auto;
      padding: 0 16px 240px 16px;
    }
    .t1 {
      margin: 4px 0;
      padding: 8px;
      background-color: #fff5f5;
    }
    .t2 {
      padding: 2px;
      display: inline-block;
      vertical-align: top;
    }
    .t3 {
      padding: 0;
      display: inline-block;
      width: 100%;
    }
    .entry-links {
      width: 10%;
    }
    .entry-paper {
      width: 87%;
    }
    .entry-control {
      width: 2%;
    }
    .entry-id, .entry-title{
      font-weight: 700;
    }
    .entry-authors{
      font-size: 90%;
      font-style: italic;
    }
    .entry-abstract, .entry-comments-all{
      font-size: 90%;
      padding-top: 8px;
    }
    .entry-comments{
        padding-top: 4px;
    }
    .options {
      margin-bottom: 15px;
    }
    .options div{
      display: inline-block;
      width: 55%;
    }
    .options div:last-child{
      text-align: right;
      width: 44%;
    }
    .options label{
      display: inline-block;
      padding: 6px;
    }
    @media (max-width: 800px) {
      .t2 {
        width: 100%;
      }
      .t3, .mobile_label{
        display: inline;
      }
    }
    .entries {
      margin-bottom: 36px;
    }

    .header {
      text-align: center;
      margin-bottom: 16px;
    }
    .hide{
      display: none;
    }
  </style>
""")
    parts.append("</head>")
    parts.append("<body>")
    parts.append('  <div class="content">')
    parts.append('    <h1>Mao Astro Group Paper Discussion</h1>')
    parts.append('    <div class="options">')
    parts.append('      <div>')
    parts.append('        <label><input type="checkbox" name="show-abs"> Show Abstracts</label>')
    parts.append('        <label><input type="checkbox" checked name="show-cm"> Show Comments</label>')
    parts.append('      </div>')
    parts.append('      <div>')
    parts.append(f'        <i>Generated at {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}</i>')
    parts.append('      </div>')
    parts.append('    </div>')  # options
    parts.append('    <div class="entries">')

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

        parts.append(
            f'          <div class="t3 entry-title">{str2html(meta.get("title", ""))}</div>'

        )

        parts.append(
            '          <div class="t3 entry-authors">{authors}{more}</div>'.format(
                authors=str2html(", ".join(meta.get("authors", []))),
                more=(" et al." if meta.get("has_more_authors") else ""),
            )
        )

        parts.append("        </div>")  # entry-paper

        parts.append(f'        <div class="t2 entry-control"><a class="t3" href="javascript:toggle(\'abs-{row["index"]}\')">📖</a><a class="t3" href="javascript:toggle(\'cm-{row["index"]}\')">💬</a></div>')

        parts.append(
            f'        <div class="t2 entry-abstract hide" id="abs-{row["index"]}">{str2html(meta.get("abstract", ""))}</div>'
        )

        parts.append('        <div class="t2 entry-comments-all" id="cm-{}">'.format(row["index"]))
        for name, date, comments in row["comments"]:
            comments_formatted = (": " + str2html(comments)) if comments else ""
            parts.append(
                f'          <div class="t3 entry-comments"><b>{str2html(name)}</b> ({str2html(date)}){comments_formatted}</div>'
            )
        parts.append("        </div>")  # entry-comments-all

        parts.append("      </div>")  # entry

    parts.append("    </div>")  # entries
    parts.append("  </div>")  # page
    parts.append('''
  <script>
    document.querySelectorAll(".t1").forEach((row, i) => {
      row.dataset.color = (i % 2) ? "#ddd" : "#eee";
      row.style.backgroundColor = row.dataset.color;
      row.addEventListener("mouseenter", () => {row.style.backgroundColor = "#fff";});
      row.addEventListener("mouseleave", () => {row.style.backgroundColor = row.dataset.color;});
    });

    const toggle = function(id) {
      document.getElementById(id).classList.toggle("hide");
    };

    const showAbsAll = function() {
      const checked = document.querySelector('input[name="show-abs"]').checked;
      if (checked) {
        document.querySelectorAll(".entry-abstract").forEach((abs) => {abs.classList.remove("hide");});
      } else {
        document.querySelectorAll(".entry-abstract").forEach((abs) => {abs.classList.add("hide");});
      }
    };
    document.querySelector('input[name="show-abs"]').addEventListener("change", showAbsAll);

    const showCmAll = function() {
      const checked = document.querySelector('input[name="show-cm"]').checked;
      if (checked) {
        document.querySelectorAll(".entry-comments-all").forEach((cm) => {cm.classList.remove("hide");});
      } else {
        document.querySelectorAll(".entry-comments-all").forEach((cm) => {cm.classList.add("hide");});
      }
    };
    document.querySelector('input[name="show-cm"]').addEventListener("change", showCmAll);

  </script>
''')
    parts.append("</body>")
    parts.append("</html>")

    return "\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate an HTML page from a CSV of arXiv IDs."
    )
    parser.add_argument("input_csv", help="Path to input CSV file.")
    parser.add_argument("output_html", help="Path to output HTML file.")
    parser.add_argument("--cache", help="Path to cache file.")
    args = parser.parse_args(argv)

    rows = process_csv_rows(read_csv(args.input_csv))
    arxiv_ids = [row["arxiv_id"] for row in rows]

    if args.cache and os.path.exists(args.cache):
        with open(args.cache, "r") as f:
            metadata_by_id = json.load(f)
    else:
        metadata_by_id = None

    metadata_by_id = fetch_arxiv_metadata(arxiv_ids, metadata_by_id)

    if args.cache:
        with open(args.cache, "w") as f:
            json.dump(metadata_by_id, f)

    html_text = build_html(rows, metadata_by_id)

    with open(args.output_html, "w") as f:
        f.write(html_text)

    return


if __name__ == "__main__":
    main()
