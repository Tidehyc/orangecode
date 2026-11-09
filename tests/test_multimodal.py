from pathlib import Path

from orangecode.context.assembler import ContextAssembler
from orangecode.spine.message import (
    Media,
    build_user_content,
    detect_image_mime,
    safe_name,
    save_media_bytes,
)
from orangecode.utils.token_counter import estimate_prompt_tokens


def test_safe_name():
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("/var/log/app.log") == "app.log"
    assert safe_name("") == "file"
    assert safe_name(None) == "file"


def test_save_media_bytes(tmp_path: Path):
    data = b"sample image bytes 12345"
    saved = save_media_bytes(tmp_path, data, name="chart.png")
    assert saved.is_file()
    assert saved.name.endswith("_chart.png")
    assert saved.read_bytes() == data


def test_detect_image_mime():
    assert detect_image_mime(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") == "image/png"
    assert detect_image_mime(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01") == "image/jpeg"
    assert detect_image_mime(b"GIF89a\x01\x00\x01\x00\x80\x00\x00") == "image/gif"
    assert detect_image_mime(b"RIFF\x1a\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert detect_image_mime(b"plain text data") is None


def test_build_user_content_text_only():
    res = build_user_content("Hello, agent!", media=None)
    assert res == "Hello, agent!"


def test_build_user_content_with_media_bytes():
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdummy"
    media = [
        Media(path="dummy.png", content=png_bytes, mime="image/png"),
    ]
    res = build_user_content("Describe this image", media=media)
    assert isinstance(res, list)
    assert len(res) == 2
    assert res[0]["type"] == "image_url"
    assert res[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert res[1] == {"type": "text", "text": "Describe this image"}


def test_build_user_content_with_attachment_notes(tmp_path: Path):
    doc_path = tmp_path / "notes.txt"
    doc_path.write_text("my notes content", encoding="utf-8")

    res = build_user_content("Please summarize", media=[str(doc_path)])
    assert isinstance(res, str)
    assert "Please summarize" in res
    assert "[Attachment: notes.txt" in res


def test_context_assembler_multimodal():
    assembler = ContextAssembler()
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdummy"
    media = [Media(path="img.png", content=png_bytes, mime="image/png")]

    messages, outcome = assembler.assemble(
        system_prompt="You are helpful.",
        history=[],
        current_prompt="What is this?",
        media=media,
    )
    assert outcome.ok
    user_msg = messages[-1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["type"] == "image_url"

    # Token counter handles multimodal content without crashing
    tokens = estimate_prompt_tokens(messages)
    assert tokens > 0
