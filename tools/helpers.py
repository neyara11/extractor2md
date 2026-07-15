"""Document loader helpers."""

import concurrent.futures
import re
from pathlib import Path
from typing import NamedTuple, Optional, cast


class FileEncoding(NamedTuple):
    """A file encoding as the NamedTuple."""

    encoding: Optional[str]
    """The encoding of the file."""
    confidence: float
    """The confidence of the encoding."""
    language: Optional[str]
    """The language of the file."""


def detect_file_encodings(file_bytes: bytes, timeout: int = 5) -> list[FileEncoding]:
    """Try to detect the file encoding from bytes.

    Args:
        file_bytes: file bytes
        timeout: timeout in seconds
    """
    import chardet
    from io import BytesIO
    import csv

    def try_decode(data: bytes, encoding: str) -> bool:
        try:
            with BytesIO(data) as f:
                csv.Sniffer().sniff(f.read(1024).decode(encoding))
            return True
        except:
            return False

    def read_and_detect(data: bytes) -> list[dict]:
        raw_results = chardet.detect_all(data) or [chardet.detect(data)]

        valid_results = []
        for result in raw_results:
            if result["encoding"] and try_decode(data, result["encoding"]):
                valid_results.append(result)

        return valid_results or raw_results

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(read_and_detect, file_bytes)
        try:
            encodings = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError("Timeout reached while detecting encoding")

    if all(encoding["encoding"] is None for encoding in encodings):
        raise RuntimeError("Could not detect encoding")
    return [FileEncoding(**enc) for enc in encodings if enc["encoding"] is not None]


def markdown_to_tups(markdown_text: str) -> list[tuple[Optional[str], str]]:
    """Split markdown text into (header, content) tuples at heading boundaries.

    Headers are detected as lines matching ``^#+\\s`` outside of code blocks.
    Returns a list of ``(header_text_or_None, section_content)`` tuples.
    """
    markdown_tups: list[tuple[Optional[str], str]] = []
    lines = markdown_text.split("\n")

    current_header = None
    current_text = ""
    code_block_flag = False

    for line in lines:
        if line.startswith("```"):
            code_block_flag = not code_block_flag
            current_text += line + "\n"
            continue
        if code_block_flag:
            current_text += line + "\n"
            continue
        header_match = re.match(r"^#+\s", line)
        if header_match:
            markdown_tups.append((current_header, current_text))
            current_header = line
            current_text = ""
        else:
            current_text += line + "\n"
    markdown_tups.append((current_header, current_text))

    markdown_tups = [
        (re.sub(r"^#+\s*", "", cast(str, key)).strip() if key else None, re.sub(r"<.*?>", "", value))
        for key, value in markdown_tups
    ]

    return markdown_tups
