import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.extractor2md import DifyExtractorTool


class _MessageToolMixin:
    def create_text_message(self, value):
        return {"type": "text", "value": value}

    def create_variable_message(self, name, value):
        return {"type": "variable", "name": name, "value": value}


def _make_tool() -> DifyExtractorTool:
    tool = object.__new__(DifyExtractorTool)
    tool.create_text_message = _MessageToolMixin.create_text_message.__get__(tool, DifyExtractorTool)
    tool.create_variable_message = _MessageToolMixin.create_variable_message.__get__(tool, DifyExtractorTool)
    return tool


def test_invoke_returns_error_for_corrupt_docx():
    tool = _make_tool()
    corrupt_file = SimpleNamespace(filename="report.docx", blob=b"not a zip file")

    messages = list(tool._invoke({"file": corrupt_file}))

    assert len(messages) == 1
    assert messages[0]["type"] == "text"
    assert "not a valid .docx file" in messages[0]["value"]
    assert "old binary .doc instead of .docx" in messages[0]["value"]


def test_invoke_returns_error_for_corrupt_pptx():
    tool = _make_tool()
    corrupt_file = SimpleNamespace(filename="slides.pptx", blob=b"not a zip file")

    messages = list(tool._invoke({"file": corrupt_file}))

    assert len(messages) == 1
    assert messages[0]["type"] == "text"
    assert "not a valid .pptx file" in messages[0]["value"]
    assert "old binary .ppt instead of .pptx" in messages[0]["value"]


def test_invoke_returns_error_for_corrupt_xlsx():
    tool = _make_tool()
    corrupt_file = SimpleNamespace(filename="sheet.xlsx", blob=b"not a zip file")

    messages = list(tool._invoke({"file": corrupt_file}))

    assert len(messages) == 1
    assert messages[0]["type"] == "text"
    assert "not a valid .xlsx file" in messages[0]["value"]
    assert "old binary .xls instead of .xlsx" in messages[0]["value"]


def test_markdown_to_tups_splits_on_headers():
    from tools.helpers import markdown_to_tups

    result = markdown_to_tups("# Title\ncontent\n## Section\nmore content")

    assert len(result) == 3
    assert result[0] == (None, "")
    assert result[1] == ("Title", "content\n")
    assert result[2] == ("Section", "more content\n")


def test_markdown_to_tups_no_headers():
    from tools.helpers import markdown_to_tups

    result = markdown_to_tups("just text\nno headers")

    assert len(result) == 1
    assert result[0] == (None, "just text\nno headers\n")


def test_markdown_to_tups_ignores_headers_in_code_blocks():
    from tools.helpers import markdown_to_tups

    content = "# Real Header\ntext\n```\n# Not a header\n```\n## Another Header\nmore"
    result = markdown_to_tups(content)

    assert len(result) == 3
    assert result[1] == ("Real Header", "text\n```\n# Not a header\n```\n")
    assert result[2] == ("Another Header", "more\n")


def test_word_extractor_heading_level():
    from tools.word_extractor import WordExtractor

    assert WordExtractor._get_heading_level("Heading 1") == 1
    assert WordExtractor._get_heading_level("heading 3") == 3
    assert WordExtractor._get_heading_level("Heading 6") == 6
    assert WordExtractor._get_heading_level("title") == 1
    assert WordExtractor._get_heading_level("Subtitle") == 2
    assert WordExtractor._get_heading_level("Normal") == 0
    assert WordExtractor._get_heading_level("") == 0


def test_html_extractor_converts_h_tags():
    from tools.html_extractor import HtmlExtractor

    extractor = HtmlExtractor(
        b"<html><body><h1>Title</h1><p>Paragraph</p><h2>Section</h2><p>More</p></body></html>",
        "test.html",
    )
    result = extractor.extract()

    assert "# Title" in result.md_content
    assert "## Section" in result.md_content
    assert "Paragraph" in result.md_content
    assert len(result.documents) >= 2


def test_html_extractor_handles_empty():
    from tools.html_extractor import HtmlExtractor

    extractor = HtmlExtractor(b"<html><body></body></html>", "test.html")
    result = extractor.extract()

    assert result.md_content == ""
    assert len(result.documents) == 0
