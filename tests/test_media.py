from pathlib import Path

from app.services.media import extension_for, secure_filename


def test_secure_filename_removes_path_and_unsafe_characters():
    assert secure_filename("../My File (final).mp4") == "My_File_final_.mp4"


def test_secure_filename_falls_back_for_empty_name():
    assert secure_filename("...").startswith("upload_")


def test_extension_for_normalizes_suffix():
    assert extension_for("voice.MP3") == "mp3"
    assert extension_for(str(Path("nested") / "clip.webm")) == "webm"

