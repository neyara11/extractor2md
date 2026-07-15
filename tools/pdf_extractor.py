import io
import logging
import mimetypes
import uuid
from io import BytesIO

from dify_plugin import Tool

from tools.document import Document, ExtractorResult
from tools.extractor_base import BaseExtractor
from tools.helpers import markdown_to_tups

import pypdfium2
import pypdfium2.raw as pdfium_c

logger = logging.getLogger(__name__)


class PdfExtractor(BaseExtractor):
    """Load pdf files.

    Args:
        tool: Tool instance
        file_bytes: file bytes
        file_name: file name.
    """

    IMAGE_FORMATS = [
        (b"\xff\xd8\xff", "jpg", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
        (b"\x00\x00\x00\x0c\x6a\x50\x20\x20\x0d\x0a\x87\x0a", "jp2", "image/jp2"),
        (b"GIF8", "gif", "image/gif"),
        (b"BM", "bmp", "image/bmp"),
        (b"II*\x00", "tiff", "image/tiff"),
        (b"MM\x00*", "tiff", "image/tiff"),
        (b"II+\x00", "tiff", "image/tiff"),
        (b"MM\x00+", "tiff", "image/tiff"),
    ]
    MAX_MAGIC_LEN = max(len(m) for m, _, _ in IMAGE_FORMATS)

    HEADER_SIZE_RATIO = 1.3
    SUBHEADER_SIZE_RATIO = 1.15
    BOLD_WEIGHT = 600

    def __init__(self, tool: Tool, file_bytes: bytes, file_name: str):
        self._file_bytes = file_bytes
        self._file_name = file_name
        self._tool = tool

    def extract(self) -> ExtractorResult:
        all_documents = []
        all_images = []
        all_content_parts = []
        with BytesIO(self._file_bytes) as file:
            pdf_reader = pypdfium2.PdfDocument(file, autoclose=True)
            try:
                for page_number, page in enumerate(pdf_reader):
                    content, page_img_list = self._extract_page_content(page)
                    all_images.extend(page_img_list)
                    all_content_parts.append(content)
                    tups = markdown_to_tups(content)
                    for header, value in tups:
                        value = value.strip()
                        metadata = {"source": self._file_name, "page": page_number}
                        if header:
                            metadata["section"] = header
                        if header is None:
                            if value:
                                all_documents.append(Document(page_content=value, metadata=metadata))
                        else:
                            all_documents.append(Document(page_content=f"\n\n{header}\n{value}", metadata=metadata))
            finally:
                pdf_reader.close()

        full_md = "\n\n".join(all_content_parts)
        return ExtractorResult(md_content=full_md, documents=all_documents, img_list=all_images)

    def _extract_page_content(self, page) -> tuple[str, list]:
        page_md = ""
        text_runs = self._get_text_runs_with_font(page)
        if text_runs:
            page_md = self._build_markdown_from_runs(text_runs)
        else:
            text_page = page.get_textpage()
            try:
                page_md = text_page.get_text_bounded()
            finally:
                text_page.close()

        image_content, page_img_list = self._extract_images(page)
        if image_content:
            page_md += "\n" + image_content

        return page_md, page_img_list

    def _get_text_runs_with_font(self, page) -> list[dict]:
        try:
            text_page = page.get_textpage()
        except Exception:
            return []

        try:
            objects = list(page.get_objects(
                filter=(pdfium_c.FPDF_PAGEOBJ_TEXT,),
                textpage=text_page,
            ))
        except Exception:
            logger.debug("Failed to get text objects for header detection, falling back to plain text")
            text_page.close()
            return []

        runs = []
        for obj in objects:
            try:
                font_size = obj.get_font_size()
                text = obj.extract()
                bounds = obj.get_bounds()
                font_weight = 400
                try:
                    font = obj.get_font()
                    font_weight = font.get_weight()
                except Exception:
                    pass
                if text.strip():
                    runs.append({
                        "text": text,
                        "font_size": font_size,
                        "font_weight": font_weight,
                        "y": bounds[3],
                        "x": bounds[0],
                    })
            except Exception:
                continue

        text_page.close()
        return runs

    def _build_markdown_from_runs(self, runs: list[dict]) -> str:
        if not runs:
            return ""

        runs.sort(key=lambda r: (-r["y"], r["x"]))

        font_sizes = [r["font_size"] for r in runs]
        font_sizes.sort()
        median_font_size = font_sizes[len(font_sizes) // 2] if font_sizes else 12.0

        body_size = median_font_size or 12.0

        lines = []
        current_line_y = None
        current_line_runs = []

        for run in runs:
            if current_line_y is None or abs(run["y"] - current_line_y) > body_size * 0.2:
                if current_line_runs:
                    lines.append(self._merge_line_runs(current_line_runs))
                current_line_runs = [run]
                current_line_y = run["y"]
            else:
                current_line_runs.append(run)

        if current_line_runs:
            lines.append(self._merge_line_runs(current_line_runs))

        result = []
        for line_runs in lines:
            if not line_runs:
                continue
            text = " ".join(r["text"].strip() for r in line_runs)
            max_size = max(r["font_size"] for r in line_runs)
            max_weight = max(r["font_weight"] for r in line_runs)

            if max_size >= body_size * self.HEADER_SIZE_RATIO:
                text = f"# {text}"
            elif max_size >= body_size * self.SUBHEADER_SIZE_RATIO and max_weight >= self.BOLD_WEIGHT:
                text = f"## {text}"
            elif max_size >= body_size * self.SUBHEADER_SIZE_RATIO:
                text = f"### {text}"

            result.append(text)

        return "\n\n".join(result)

    @staticmethod
    def _merge_line_runs(runs: list[dict]) -> list[dict]:
        merged = []
        for run in runs:
            if merged and run["font_size"] == merged[-1]["font_size"] and run["font_weight"] == merged[-1]["font_weight"]:
                merged[-1]["text"] += " " + run["text"]
            else:
                merged.append(dict(run))
        return merged

    def _extract_images(self, page) -> tuple[str, list]:
        image_content = []
        img_list = []

        try:
            image_objects = page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,))
            for obj in image_objects:
                try:
                    img_byte_arr = io.BytesIO()
                    obj.extract(img_byte_arr, fb_format="png")
                    img_bytes = img_byte_arr.getvalue()

                    if not img_bytes:
                        continue

                    header = img_bytes[: self.MAX_MAGIC_LEN]
                    image_ext = None
                    mime_type = None
                    for magic, ext, mime in self.IMAGE_FORMATS:
                        if header.startswith(magic):
                            image_ext = ext
                            mime_type = mime
                            break

                    if not image_ext or not mime_type:
                        continue

                    file_uuid = str(uuid.uuid4())
                    file_name = file_uuid + "." + image_ext

                    file_res = self._tool.session.file.upload(
                        file_name, img_bytes, mime_type
                    )
                    image_content.append(f"![image]({file_res.preview_url})")
                    img_list.append(file_res)
                except Exception as e:
                    logger.warning("Failed to extract image from PDF: %s", e)
                    continue
        except Exception as e:
            logger.warning("Failed to get objects from PDF page: %s", e)

        return "\n".join(image_content), img_list
