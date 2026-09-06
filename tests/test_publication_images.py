"""Publication image preparation tests."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, PngImagePlugin

from scripts.prepare_publication_image import prepare_image


def test_prepare_image_crops_to_aspect_and_strips_metadata(tmp_path: Path) -> None:
    source = tmp_path / "native.png"
    output = tmp_path / "publication.png"
    image = Image.new("RGB", (1325, 725), (32, 48, 64))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Source", "PRIVATE_SOURCE_MARKER")
    image.save(source, pnginfo=metadata)

    report = prepare_image(source, output, (1600, 900))

    assert report["source_size"] == [1325, 725]
    assert report["crop_box"] == [18, 0, 1307, 725]
    assert report["output_size"] == [1600, 900]
    assert b"PRIVATE_SOURCE_MARKER" not in output.read_bytes()
    with Image.open(output) as prepared:
        assert prepared.size == (1600, 900)
        assert prepared.mode == "RGB"
        assert not prepared.info
