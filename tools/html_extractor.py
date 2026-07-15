"""Abstract interface for document loader implementations."""

from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag  # type: ignore

from tools.extractor_base import BaseExtractor
from tools.document import Document, ExtractorResult
from tools.helpers import markdown_to_tups

HEADING_TAGS = frozenset({f"h{i}" for i in range(1, 7)})
SKIP_TAGS = frozenset({"script", "style", "noscript", "meta", "link", "head"})

_SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto", "ftp"})


class HtmlExtractor(BaseExtractor):
    """Load html files.

    Args:
        file_bytes: HTML content in bytes format.
        file_name: file name.
    """

    def __init__(self, file_bytes: bytes, file_name: str):
        """Initialize with file bytes."""
        self._file_bytes = file_bytes
        self._file_name = file_name

    def extract(self) -> ExtractorResult:
        text = self._load_as_markdown()
        tups = markdown_to_tups(text)
        documents = []
        for header, value in tups:
            value = value.strip()
            metadata = {"source": self._file_name}
            if header:
                metadata["section"] = header
            if header is None:
                if value:
                    documents.append(Document(page_content=value, metadata=metadata))
            else:
                documents.append(Document(page_content=f"\n\n{header}\n{value}", metadata=metadata))
        return ExtractorResult(
            md_content=text,
            documents=documents,
        )

    def _load_as_markdown(self) -> str:
        from io import BytesIO

        with BytesIO(self._file_bytes) as fp:
            soup = BeautifulSoup(fp, "html.parser")
        return self._node_to_markdown(soup).strip()

    def _node_to_markdown(self, node) -> str:
        if isinstance(node, NavigableString):
            return str(node)

        if not isinstance(node, Tag):
            return ""

        tag = node.name.lower() if node.name else ""
        if tag in SKIP_TAGS:
            return ""

        children_md = "".join(self._node_to_markdown(c) for c in node.children)

        if tag in HEADING_TAGS:
            level = int(tag[1])
            text = self._strip_nested(children_md)
            return f"\n\n{'#' * level} {text}\n\n"

        if tag == "p":
            text = children_md.strip()
            return f"\n\n{text}\n\n" if text else "\n\n"

        if tag == "br":
            return "\n"

        if tag in {"strong", "b"}:
            text = children_md.strip()
            return f"**{text}**" if text else ""

        if tag in {"em", "i"}:
            text = children_md.strip()
            return f"*{text}*" if text else ""

        if tag == "code":
            text = children_md.strip()
            return f"`{text}`" if text else ""

        if tag == "a":
            href = node.get("href", "")
            text = children_md.strip() or href
            if href and self._is_safe_url(href):
                return f"[{text}]({href})"
            return text if text else ""

        if tag == "img":
            alt = node.get("alt", "")
            src = node.get("src", "")
            if src and self._is_safe_url(src):
                return f"![{alt}]({src})"
            return ""

        if tag == "pre":
            text = children_md.rstrip()
            return f"\n\n```\n{text}\n```\n\n" if text else ""

        if tag in {"ul", "ol"}:
            return f"\n{children_md}\n"

        if tag == "li":
            parent_tag = node.parent.name.lower() if node.parent and hasattr(node.parent, "name") else ""
            text = self._strip_nested(children_md).strip()
            if parent_tag == "ol":
                order_prefix = self._get_li_index(node) + 1
                return f"{order_prefix}. {text}\n" if text else ""
            return f"- {text}\n" if text else ""

        if tag == "table":
            return self._table_to_markdown(node)

        if tag in {"tr", "td", "th", "thead", "tbody", "tfoot"}:
            return children_md

        if tag == "blockquote":
            return f"\n> {children_md.strip()}\n"

        if tag == "hr":
            return "\n---\n"

        if tag in {"div", "section", "article", "main", "header", "footer", "nav", "aside", "figure", "figcaption"}:
            return f"\n\n{children_md}\n\n"

        return children_md

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        if not url:
            return False
        if url.startswith("/") or url.startswith("#") or url.startswith("."):
            return True
        parsed = urlparse(url)
        return parsed.scheme.lower() in _SAFE_URL_SCHEMES

    @staticmethod
    def _strip_nested(text: str) -> str:
        return text.strip().replace("\n", " ")

    @staticmethod
    def _get_li_index(li_tag: Tag) -> int:
        parent = li_tag.parent
        if not parent:
            return 0
        li_tags = parent.find_all("li", recursive=False)
        for idx, child in enumerate(li_tags):
            if child is li_tag:
                return idx
        return 0

    @staticmethod
    def _table_to_markdown(table_tag: Tag) -> str:
        rows = table_tag.find_all("tr")
        if not rows:
            return ""

        all_cells = []
        max_cols = 0
        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(strip=True) for c in cells]
            all_cells.append(cell_texts)
            if len(cell_texts) > max_cols:
                max_cols = len(cell_texts)

        if max_cols == 0:
            return ""

        md = ""
        for i, row_cells in enumerate(all_cells):
            padded = row_cells + [""] * (max_cols - len(row_cells))
            md += "| " + " | ".join(padded) + " |\n"
            if i == 0:
                md += "| " + " | ".join(["---"] * max_cols) + " |\n"
        return f"\n{md}\n"
