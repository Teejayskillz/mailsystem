"""Email HTML sanitisation.

Two layers of defence:
  1. ``nh3`` (Rust ammonia binding) rebuilds the HTML from an allow-list.
  2. The result is served inside a sandboxed iframe with a restrictive CSP,
     so even a sanitiser bypass cannot run scripts in the dashboard origin.

Images are deliberately not allowed: remote images are tracking pixels, and
inline attachments are out of scope for this MVP.
"""

from __future__ import annotations

import html

import nh3

ALLOWED_TAGS: set[str] = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "col", "colgroup",
    "dd", "div", "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "i", "li", "ol", "p", "pre", "s", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
}

ALLOWED_SCHEMES: set[str] = {"http", "https", "mailto"}

# Inline CSS for the sandboxed render document. Email stylesheets are stripped;
# this is the only CSS the iframe ever receives.
DOCUMENT_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    font-size: 15px; line-height: 1.55; margin: 0; padding: 18px 20px;
    color: #1f2328; background: #ffffff; overflow-wrap: anywhere;
  }
  a { color: #0b5ed7; }
  pre, code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; }
  pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
  blockquote { margin: 0 0 0 4px; padding-left: 12px; border-left: 3px solid #d0d7de; color: #57606a; }
  table { border-collapse: collapse; max-width: 100%; }
  td, th { border: 1px solid #d0d7de; padding: 6px 10px; vertical-align: top; }
  hr { border: 0; border-top: 1px solid #d0d7de; margin: 16px 0; }
  .mailgen-empty { color: #57606a; font-style: italic; }
  @media (prefers-color-scheme: dark) {
    body { background: #0d1117; color: #e6edf3; }
    a { color: #6ea8fe; }
    pre { background: #161b22; }
    blockquote { border-left-color: #30363d; color: #8b949e; }
    td, th { border-color: #30363d; }
  }
"""


class SanitisationError(Exception):
    pass


def sanitize_email_html(raw_html: str) -> str:
    """Return an allow-listed HTML fragment. Never raises for bad input."""
    if not raw_html:
        return ""

    try:
        return nh3.clean(
            raw_html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes=ALLOWED_SCHEMES,
            link_rel="noopener noreferrer nofollow",
            strip_comments=True,
        )
    except Exception as exc:  # pragma: no cover - nh3 is very tolerant
        raise SanitisationError("The message HTML could not be sanitised safely.") from exc


def document_from_html(fragment: str, title: str = "Message") -> str:
    body = fragment or '<p class="mailgen-empty">This message has no HTML body.</p>'
    return _wrap(body, title)


def document_from_text(text: str, title: str = "Message") -> str:
    body = f"<pre>{html.escape(text)}</pre>" if text else (
        '<p class="mailgen-empty">This message has no readable body.</p>'
    )
    return _wrap(body, title)


def _wrap(body: str, title: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{DOCUMENT_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
