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
import urllib.parse
import urllib.request

import feedparser

ARXIV_API_URL = "http://export.arxiv.org/api/query"

# CSV column names (adjust here if your CSV uses different headers)
DATE_FIELD = "date"
NAME_FIELD = "name"
ARXIV_ID_FIELD = "arXiv ID"
COMMENTS_FIELD = "comments"

# Your arXiv ID regex
RE_ARXIV_ID = re.compile(
    r"\b(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Za-z-]+)?/\d{7})\b",
    flags=re.IGNORECASE,
)


def normalize_arxiv_id(raw_arxiv_id):
    """Extract canonical arXiv ID from any reasonable string.

    - Uses RE_ARXIV_ID to locate either a new-style (YYMM.NNNN/NNNNN)
      or old-style (archive/NNNNNNN) arXiv identifier.
    - Returns the ID in lowercase, without version info, or empty string if
      nothing can be found.
    """
    m = RE_ARXIV_ID.search(raw_arxiv_id)
    if not m:
        return
    return m.group(0).lower()


def fetch_arxiv_metadata(arxiv_ids, existing_metadata=None):
    """
    Fetch metadata from arXiv for a list of arXiv IDs.

    Parameters
    ----------
    arxiv_ids : Iterable[str]
        List of arXiv IDs (any reasonable form; they will be normalized).

    Returns
    -------
    dict
        Mapping from canonical arXiv ID (without version, lowercase)
        to a dictionary with keys: id, title, authors, abstract, url, pdf_url.
    """

    metadata = existing_metadata or {}

    # Normalize and deduplicate
    normalized_arxiv_ids = []
    for raw_arxiv_id in arxiv_ids:
        arxiv_id = normalize_arxiv_id(raw_arxiv_id)
        if not arxiv_id:
            continue
        if arxiv_id in metadata:
            continue
        if arxiv_id in normalized_arxiv_ids:
            continue
        normalized_arxiv_ids.append(arxiv_id)

    if not normalized_arxiv_ids:
        return metadata

    BATCH_SIZE = 50

    for start in range(0, len(normalized_arxiv_ids), BATCH_SIZE):
        batch = normalized_arxiv_ids[start:(start+BATCH_SIZE)]
        ids_param = ",".join(batch)
        params = urllib.parse.urlencode({"id_list": ids_param})
        url = f"{ARXIV_API_URL}?{params}"

        with urllib.request.urlopen(url) as response:
            data = response.read()

        feed = feedparser.parse(data)

        for entry in feed.entries:
            # entry.id is usually a URL like 'http://arxiv.org/abs/1234.5678v1'
            base_id = normalize_arxiv_id(entry.get("id", ""))
            if not base_id:
                continue

            authors = [a.get("name", "").strip() for a in entry.get("authors", [])]
            authors = [a for a in authors if a]
            authors = authors[:6]

            title = entry.get("title", "").strip().replace("\n", " ")
            abstract = entry.get("summary", "").strip()

            arxiv_url = None
            pdf_url = None
            for link in entry.get("links", []):
                href = link.get("href")
                if not href:
                    continue
                rel = link.get("rel", "").lower()
                title_attr = (link.get("title") or "").lower()
                if rel == "alternate":
                    arxiv_url = href
                if title_attr == "pdf":
                    pdf_url = href

            if not arxiv_url:
                arxiv_url = f"https://arxiv.org/abs/{base_id}"
            if not pdf_url:
                pdf_url = f"https://arxiv.org/pdf/{base_id}.pdf"

            metadata[base_id] = {
                "id": base_id,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "url": arxiv_url,
                "pdf_url": pdf_url,
            }

    return metadata


def read_csv(path):
    """Read the input CSV file and return a list of row dictionaries."""
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def build_html(rows, metadata_by_id):
    """Build the HTML string for all rows using the provided metadata."""
    parts = []

    parts.append("<!DOCTYPE html>")
    parts.append("<html>")
    parts.append("<head>")
    parts.append('  <meta charset="utf-8">')
    parts.append("  <title>arXiv Entries</title>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append('  <div class="page">')
    parts.append('    <div class="entries">')

    for row in rows:
        date = (row.get(DATE_FIELD) or "").strip()
        name = (row.get(NAME_FIELD) or "").strip()
        comments = (row.get(COMMENTS_FIELD) or "").strip()
        raw_arxiv_id = (row.get(ARXIV_ID_FIELD) or "").strip()

        canonical_id = normalize_arxiv_id(raw_arxiv_id)
        meta = metadata_by_id.get(canonical_id)

        parts.append('      <div class="entry">')

        # Header: date and name
        parts.append('        <div class="entry-header">')
        parts.append(
            '          <div class="entry-date">{}</div>'.format(
                html.escape(date, quote=True)
            )
        )
        parts.append(
            '          <div class="entry-name">{}</div>'.format(
                html.escape(name, quote=True)
            )
        )
        parts.append("        </div>")  # entry-header

        # Comments from CSV
        if comments:
            comments_html = "<br>".join(
                html.escape(line, quote=True) for line in comments.splitlines()
            )
            parts.append(
                f'        <div class="entry-comments">{comments_html}</div>'
            )

        # arXiv ID / URL
        if raw_arxiv_id:
            if meta and meta.get("url"):
                arxiv_url = meta["url"]
            else:
                nid_for_url = canonical_id
                arxiv_url = (
                    f"https://arxiv.org/abs/{nid_for_url}" if nid_for_url else ""
                )

            if arxiv_url:
                parts.append('        <div class="entry-arxiv">')
                parts.append(
                    '          <div class="entry-arxiv-id"><a href="{url}">{label}</a></div>'.format(
                        url=html.escape(arxiv_url, quote=True),
                        label=html.escape(raw_arxiv_id, quote=True),
                    )
                )
                parts.append("        </div>")  # entry-arxiv

        # Metadata from arXiv
        if meta:
            authors = meta.get("authors") or []
            authors_str = ", ".join(authors[:6])

            parts.append(
                '        <div class="entry-title">{}</div>'.format(
                    html.escape(meta.get("title", ""), quote=True)
                )
            )
            if authors_str:
                parts.append(
                    '        <div class="entry-authors">{}</div>'.format(
                        html.escape(authors_str, quote=True)
                    )
                )

            abstract = meta.get("abstract", "")
            if abstract:
                abstract_html = "<br>".join(
                    html.escape(line, quote=True)
                    for line in abstract.splitlines()
                )
                parts.append(
                    f'        <div class="entry-abstract">{abstract_html}</div>'
                )
        else:
            parts.append(
                '        <div class="entry-metadata-missing">'
                "Metadata not found for this arXiv ID."
                "</div>"
            )

        parts.append("      </div>")  # entry

    parts.append("    </div>")  # entries
    parts.append("  </div>")  # page
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

    rows = read_csv(args.input_csv)

    # Collect all arXiv IDs from the CSV
    arxiv_ids = [row.get(ARXIV_ID_FIELD, "").strip() for row in rows]

    if args.cache:
        with open(args.cache, "r") as f:
            metadata_by_id = json.load(f)

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
