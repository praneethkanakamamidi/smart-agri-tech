"""
Image preparation for vision models: decode-validate, honour EXIF orientation, downscale, and
re-encode as JPEG. Re-encoding drops all metadata (including GPS location) so it never reaches
a model provider, and a file that isn't a real image fails here rather than at the provider.
"""
import asyncio
import io

MAX_PIXELS = 40_000_000  # decompression-bomb guard, well below Pillow's own limit


class ImageRejected(ValueError):
    pass


def _prepare(content: bytes, max_edge: int) -> tuple[bytes, str, dict]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(content)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise ImageRejected("image dimensions are too large")
            original = {"width": img.width, "height": img.height, "format": img.format}
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((max_edge, max_edge))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=88, optimize=True)
            return out.getvalue(), "image/jpeg", {**original, "sent_width": img.width, "sent_height": img.height}
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise ImageRejected("the file is not a readable image") from e


async def prepare_image(content: bytes, max_edge: int) -> tuple[bytes, str, dict]:
    return await asyncio.to_thread(_prepare, content, max_edge)
