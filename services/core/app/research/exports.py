"""Report exports: Markdown passthrough, DOCX via python-docx, PDF via
WeasyPrint.

Bengali honesty rule: a PDF is only produced when WeasyPrint is installed
AND a Bengali-capable font is present on the system. Otherwise
``ExportUnavailable`` is raised with the exact reason — a PDF with tofu
boxes instead of Bengali glyphs must never be shipped silently.
"""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


class ExportUnavailable(Exception):
    """An export format cannot be produced in this environment."""


def export_markdown(markdown: str, sources: list[dict], out_path: Path) -> Path:
    """Markdown export: the report itself, with a source list appended if
    the report does not already end with one."""
    text = markdown.rstrip() + "\n"
    if sources and "## Sources" not in text and "## তথ্যসূত্র" not in text:
        lines = [text, "\n## Sources\n"]
        for i, src in enumerate(sources, 1):
            title = src.get("title") or src.get("url", "")
            lines.append(f"{i}. [{title}]({src.get('url', '')})")
        text = "\n".join(lines) + "\n"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def _plain(line: str) -> str:
    """Markdown inline markup -> plain text (links keep text + URL)."""
    line = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", line)
    line = _BOLD_RE.sub(r"\1", line)
    return line.replace("`", "").strip()


def _blocks(markdown: str):
    """Yield (kind, text) blocks: h1/h2/h3, bullet, para."""
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            yield "h3", _plain(line[4:])
        elif line.startswith("## "):
            yield "h2", _plain(line[3:])
        elif line.startswith("# "):
            yield "h1", _plain(line[2:])
        elif re.match(r"^[-*]\s+", line):
            yield "bullet", _plain(re.sub(r"^[-*]\s+", "", line))
        elif re.match(r"^\d+[.)]\s+", line):
            yield "bullet", _plain(re.sub(r"^\d+[.)]\s+", "", line))
        else:
            yield "para", _plain(line)


def export_docx(markdown: str, sources: list[dict], out_path: Path) -> Path:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - env dependent
        raise ExportUnavailable(
            "DOCX export needs the 'python-docx' package, which is not installed"
        ) from exc
    doc = Document()
    for kind, text in _blocks(markdown):
        if kind in ("h1", "h2", "h3"):
            doc.add_heading(text, level=int(kind[1]))
        elif kind == "bullet":
            doc.add_paragraph(text, style="List Bullet")
        else:
            doc.add_paragraph(text)
    if sources:
        doc.add_heading("Sources", level=1)
        for i, src in enumerate(sources, 1):
            title = src.get("title") or src.get("url", "")
            doc.add_paragraph(f"{i}. {title} — {src.get('url', '')}")
    doc.save(str(out_path))
    return out_path


def bengali_font_available() -> bool:
    """True when fontconfig reports at least one Bengali (bn) font."""
    try:
        out = subprocess.run(
            ["fc-list", ":lang=bn", "family"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    # Fallback: look for known Bengali font files directly.
    for fonts_dir in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if fonts_dir.is_dir() and any(
            "bengali" in p.name.lower() for p in fonts_dir.rglob("*.ttf")
        ):
            return True
    return False


def _to_html(markdown: str, sources: list[dict]) -> str:
    parts = []
    for kind, text in _blocks(markdown):
        esc = html.escape(text)
        if kind in ("h1", "h2", "h3"):
            parts.append(f"<{kind}>{esc}</{kind}>")
        elif kind == "bullet":
            parts.append(f"<li>{esc}</li>")
        else:
            parts.append(f"<p>{esc}</p>")
    if sources:
        parts.append("<h1>Sources</h1><ol>")
        for src in sources:
            title = html.escape(src.get("title") or src.get("url", ""))
            url = html.escape(src.get("url", ""))
            parts.append(f'<li>{title} — <a href="{url}">{url}</a></li>')
        parts.append("</ol>")
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        "body { font-family: 'Noto Sans Bengali', 'Noto Serif Bengali', "
        "sans-serif; margin: 2.5cm; line-height: 1.5; }"
        "</style></head><body>" + "\n".join(parts) + "</body></html>"
    )


def export_pdf(markdown: str, sources: list[dict], out_path: Path) -> Path:
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise ExportUnavailable(
            "PDF export needs the 'weasyprint' package, which is not installed"
        ) from exc
    if not bengali_font_available():
        raise ExportUnavailable(
            "PDF export refused: no Bengali-capable font found on this "
            "system (e.g. 'Noto Sans Bengali'); Bengali text would render "
            "as blank boxes"
        )
    HTML(string=_to_html(markdown, sources)).write_pdf(str(out_path))
    return out_path


EXPORTERS = {"md": export_markdown, "docx": export_docx, "pdf": export_pdf}
MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
