"""A person's scanned signature, fitted to whatever document is signing.

Every document with a signature block leaves a gap above the name for a wet
signature. This puts the scan in that gap — and the whole job is doing it
without distorting anything, because each document's block is a different
shape: the quotation's is wide and short, the customer PO's narrower.

So nothing here has a fixed size. A caller passes the box it has, and gets
back an image scaled to fit *inside* it with the aspect ratio intact, or
`None` if there is no usable signature — in which case the block renders
exactly as it always did, an empty space to sign by hand.

Accepting the file is deliberately strict. It is drawn onto documents that
go to customers, so a corrupt or enormous upload has to fail at the point
somebody can still fix it, not halfway through generating a PDF.
"""

from __future__ import annotations

import io

# Anything larger is a photograph of a signature, not a signature. Kept well
# under the general attachment ceiling because this one is embedded in every
# PDF the person signs — a 15 MB scan would bloat every document.
MAX_BYTES = 2 * 1024 * 1024
ALLOWED = {"image/png", "image/jpeg", "image/webp"}
# PNG first: a transparent background is what lets the scan sit over the rule
# in the signature block instead of covering it with a white rectangle.
PREFERRED = "image/png"


class SignatureError(ValueError):
    """The upload cannot be used as a signature. The message is shown to the
    person uploading, so it says what to do about it."""


def validate(data: bytes, content_type: str | None) -> tuple[int, int]:
    """Check an upload and return its pixel size.

    Raises `SignatureError` with something actionable. Uses Pillow rather
    than trusting the declared content type — the browser reports whatever
    the file extension suggests, and a renamed .docx would otherwise reach
    the PDF writer.
    """
    if not data:
        raise SignatureError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise SignatureError(
            f"That image is {len(data) / 1024 / 1024:.1f} MB — the limit is "
            f"{MAX_BYTES // 1024 // 1024} MB. Crop it to just the signature "
            "and save it again.")
    try:
        from PIL import Image as PILImage
    except ImportError:                       # pragma: no cover - Pillow is a dep
        # Without Pillow we cannot verify it, and guessing is worse than
        # refusing: an unreadable file would fail inside PDF generation.
        raise SignatureError("Image support is unavailable on the server.")
    try:
        img = PILImage.open(io.BytesIO(data))
        img.verify()
        # verify() consumes the file object, so reopen for the dimensions.
        img = PILImage.open(io.BytesIO(data))
        w, h = img.size
    except Exception:
        raise SignatureError(
            "That file is not an image the app can read. Use a PNG or JPG.")
    if w < 40 or h < 20:
        raise SignatureError(
            f"That image is only {w}×{h} pixels — too small to print legibly.")
    if (content_type or "").lower() not in ALLOWED and img.format not in (
            "PNG", "JPEG", "WEBP"):
        raise SignatureError("Use a PNG, JPG or WEBP image.")
    return w, h


def fitted_flowable(data: bytes, *, max_w_mm: float, max_h_mm: float):
    """A ReportLab image scaled to fit a box, aspect ratio preserved.

    This is the "matches the format" part. The image is scaled by whichever
    of width or height runs out first, so a wide signature in a narrow block
    shrinks to fit rather than being squashed, and a small scan is never blown
    up past its own resolution into a blur.

    Returns `None` when the data cannot be drawn, so a bad signature costs a
    blank space rather than a failed document.
    """
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage

    try:
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(data))
        px_w, px_h = img.size
        if not px_w or not px_h:
            return None
    except Exception:
        return None

    box_w, box_h = max_w_mm * mm, max_h_mm * mm
    scale = min(box_w / px_w, box_h / px_h)
    # Never enlarge beyond the source: a 120px scan stretched across 60mm is
    # a blurry mess, and a signature that prints small is still a signature.
    scale = min(scale, 1.0) if px_w > box_w or px_h > box_h else scale
    w, h = px_w * scale, px_h * scale
    try:
        # mask="auto" honours PNG transparency, which is what keeps the scan
        # from painting a white rectangle over the rule beneath it.
        return RLImage(io.BytesIO(data), width=w, height=h, mask="auto")
    except Exception:
        return None


async def load_for(user) -> bytes | None:
    """The signature bytes for a user, or None. Never raises — a document
    must still generate when the file behind the path has gone missing."""
    path = getattr(user, "signature_path", None) if user else None
    if not path:
        return None
    try:
        from app.services import storage
        return await storage.load(path)
    except Exception:
        return None
