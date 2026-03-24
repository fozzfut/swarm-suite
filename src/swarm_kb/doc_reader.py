"""Shared document reader -- converts PDFs and other docs into AI-readable text.

Supports:
- PDF: multi-column, tables, headers/footers removal (via pymupdf or pdfplumber)
- Text/Markdown/RST: direct read
- CSV: table formatting
- Images in PDFs: extract descriptions where possible

Any swarm tool can use this to process documents before analysis.
"""

import logging
from pathlib import Path
from dataclasses import dataclass, field

_log = logging.getLogger("swarm_kb.doc_reader")


@dataclass
class DocumentPage:
    """A single page of parsed content."""
    page_number: int = 0
    text: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)  # list of tables, each is list of rows
    headings: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """A fully parsed document."""
    path: str = ""
    format: str = ""  # "pdf", "text", "markdown", "csv"
    total_pages: int = 0
    title: str = ""
    metadata: dict = field(default_factory=dict)  # author, creation date, etc.
    pages: list[DocumentPage] = field(default_factory=list)
    full_text: str = ""  # concatenated clean text
    tables: list[dict] = field(default_factory=list)  # all tables with page refs

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "format": self.format,
            "total_pages": self.total_pages,
            "title": self.title,
            "metadata": self.metadata,
            "full_text": self.full_text,
            "table_count": len(self.tables),
            "tables": self.tables[:50],  # limit to 50 tables in response
            "page_count": len(self.pages),
        }

    def to_ai_readable(self) -> str:
        """Convert to a clean, AI-readable text format.

        Returns structured text with:
        - Document metadata header
        - Clean text with page markers
        - Tables formatted as markdown
        - Headings preserved
        """
        parts = []
        parts.append(f"# {self.title or Path(self.path).name}")
        if self.metadata:
            for k, v in self.metadata.items():
                if v:
                    parts.append(f"- {k}: {v}")
        parts.append(f"- Pages: {self.total_pages}")
        parts.append("")

        for page in self.pages:
            parts.append(f"\n--- Page {page.page_number} ---\n")

            if page.headings:
                for h in page.headings:
                    parts.append(f"## {h}")

            # Clean text: remove excessive whitespace, fix line breaks
            clean = _clean_text(page.text)
            if clean.strip():
                parts.append(clean)

            # Format tables as markdown
            for i, table in enumerate(page.tables):
                parts.append(f"\n**Table {i+1} (page {page.page_number}):**\n")
                parts.append(_table_to_markdown(table))

        return "\n".join(parts)


def parse_document(path: str, max_pages: int = 0) -> ParsedDocument:
    """Parse a document into structured format.

    Tries multiple backends in order:
    1. pymupdf (fitz) for PDFs -- best quality
    2. pdfplumber for PDFs -- good table extraction
    3. Plain text fallback

    Args:
        path: Path to document
        max_pages: Maximum pages to parse (0 = all)

    Returns:
        ParsedDocument with clean text, tables, and metadata
    """
    p = Path(path)
    if not p.is_file():
        return ParsedDocument(path=path, format="error",
                              full_text=f"File not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(p, max_pages)
    elif suffix in (".md", ".markdown"):
        return _parse_text(p, "markdown")
    elif suffix in (".rst",):
        return _parse_text(p, "rst")
    elif suffix in (".csv", ".tsv"):
        return _parse_csv(p)
    elif suffix in (".txt", ".text", ".log", ".ini", ".cfg", ".conf"):
        return _parse_text(p, "text")
    elif suffix in (".json",):
        return _parse_text(p, "json")
    elif suffix in (".yaml", ".yml"):
        return _parse_text(p, "yaml")
    elif suffix in (".xml", ".html", ".htm"):
        return _parse_text(p, "xml")
    else:
        # Try as text
        return _parse_text(p, "text")


def _parse_pdf(path: Path, max_pages: int = 0) -> ParsedDocument:
    """Parse PDF using available backends."""
    # Try pymupdf first (best quality)
    try:
        return _parse_pdf_pymupdf(path, max_pages)
    except ImportError:
        _log.info("pymupdf not available, trying pdfplumber")

    # Try pdfplumber (good table extraction)
    try:
        return _parse_pdf_pdfplumber(path, max_pages)
    except ImportError:
        _log.info("pdfplumber not available")

    return ParsedDocument(
        path=str(path), format="pdf",
        full_text=(
            "PDF parsing requires pymupdf or pdfplumber.\n"
            "Install with: pip install pymupdf\n"
            "Or: pip install pdfplumber"
        ),
    )


def _parse_pdf_pymupdf(path: Path, max_pages: int = 0) -> ParsedDocument:
    """Parse PDF using pymupdf (fitz)."""
    import fitz  # pymupdf

    doc = fitz.open(str(path))
    result = ParsedDocument(
        path=str(path), format="pdf",
        total_pages=len(doc),
        title=doc.metadata.get("title", "") or path.stem,
        metadata={
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "creation_date": doc.metadata.get("creationDate", ""),
        },
    )

    pages_to_parse = len(doc) if max_pages == 0 else min(max_pages, len(doc))
    all_text_parts = []

    for page_num in range(pages_to_parse):
        page = doc[page_num]

        # Extract text with layout preservation
        text = page.get_text("text")

        # Extract tables
        tables = []
        try:
            page_tables = page.find_tables()
            for table in page_tables:
                extracted = table.extract()
                if extracted:
                    tables.append(extracted)
        except Exception:
            pass  # table extraction not available in all pymupdf versions

        # Detect headings (larger font text)
        headings = []
        try:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            if span["size"] > 14:  # likely a heading
                                heading_text = span["text"].strip()
                                if heading_text and len(heading_text) > 2:
                                    headings.append(heading_text)
        except Exception:
            pass

        dp = DocumentPage(
            page_number=page_num + 1,
            text=text,
            tables=tables,
            headings=headings,
        )
        result.pages.append(dp)
        all_text_parts.append(text)

        # Collect tables with page reference
        for i, table in enumerate(tables):
            result.tables.append({
                "page": page_num + 1,
                "index": i,
                "rows": len(table),
                "cols": len(table[0]) if table else 0,
                "data": table,
            })

    doc.close()
    result.full_text = "\n\n".join(all_text_parts)
    return result


def _parse_pdf_pdfplumber(path: Path, max_pages: int = 0) -> ParsedDocument:
    """Parse PDF using pdfplumber (good table extraction)."""
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        result = ParsedDocument(
            path=str(path), format="pdf",
            total_pages=len(pdf.pages),
            title=pdf.metadata.get("Title", "") or path.stem,
            metadata={
                "author": pdf.metadata.get("Author", ""),
                "creator": pdf.metadata.get("Creator", ""),
            },
        )

        pages_to_parse = len(pdf.pages) if max_pages == 0 else min(max_pages, len(pdf.pages))
        all_text_parts = []

        for page_num in range(pages_to_parse):
            page = pdf.pages[page_num]
            text = page.extract_text() or ""

            tables = []
            try:
                for table in page.extract_tables():
                    if table:
                        tables.append(table)
            except Exception:
                pass

            dp = DocumentPage(
                page_number=page_num + 1,
                text=text,
                tables=tables,
            )
            result.pages.append(dp)
            all_text_parts.append(text)

            for i, table in enumerate(tables):
                result.tables.append({
                    "page": page_num + 1,
                    "index": i,
                    "rows": len(table),
                    "cols": len(table[0]) if table else 0,
                    "data": table,
                })

        result.full_text = "\n\n".join(all_text_parts)
    return result


def _parse_text(path: Path, format_type: str) -> ParsedDocument:
    """Parse a text-based document."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return ParsedDocument(path=str(path), format="error",
                              full_text=f"Read error: {exc}")

    lines = text.split("\n")
    headings = []
    if format_type == "markdown":
        headings = [line.lstrip("#").strip() for line in lines
                    if line.startswith("#") and line.lstrip("#").strip()]

    return ParsedDocument(
        path=str(path), format=format_type,
        total_pages=1,
        title=headings[0] if headings else path.stem,
        pages=[DocumentPage(page_number=1, text=text, headings=headings)],
        full_text=text,
    )


def _parse_csv(path: Path) -> ParsedDocument:
    """Parse CSV into a document with table."""
    import csv
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        reader = csv.reader(text.splitlines())
        rows = list(reader)
    except Exception as exc:
        return ParsedDocument(path=str(path), format="error",
                              full_text=f"CSV error: {exc}")

    return ParsedDocument(
        path=str(path), format="csv",
        total_pages=1,
        title=path.stem,
        pages=[DocumentPage(page_number=1, text=text, tables=[rows])],
        full_text=text,
        tables=[{"page": 1, "index": 0, "rows": len(rows),
                 "cols": len(rows[0]) if rows else 0, "data": rows}],
    )


def _clean_text(text: str) -> str:
    """Clean extracted text: fix whitespace, remove artifacts."""
    import re
    # Remove excessive blank lines
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    # Remove page headers/footers patterns (common: page numbers, dates, doc numbers)
    text = re.sub(r'(?m)^\s*\d+\s*$', '', text)  # standalone page numbers
    text = re.sub(r'(?m)^\s*(Page|Pg\.?)\s*\d+\s*(of\s*\d+)?\s*$', '', text, flags=re.IGNORECASE)
    # Fix hyphenated line breaks
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    return text.strip()


def _table_to_markdown(table: list[list[str]]) -> str:
    """Convert a 2D table to markdown format."""
    if not table:
        return ""

    # Clean cells
    clean_table = []
    for row in table:
        clean_row = [(cell or "").strip().replace("|", "\\|").replace("\n", " ") for cell in row]
        clean_table.append(clean_row)

    # Normalize column count
    max_cols = max(len(row) for row in clean_table)
    for row in clean_table:
        while len(row) < max_cols:
            row.append("")

    # Build markdown
    lines = []
    if clean_table:
        lines.append("| " + " | ".join(clean_table[0]) + " |")
        lines.append("| " + " | ".join(["---"] * max_cols) + " |")
        for row in clean_table[1:]:
            lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)
