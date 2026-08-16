"""Compatibility shims between py-tgcalls 2.3.x and newer Pyrogram 2.0.x.

Newer Pyrogram releases removed several names that py-tgcalls 2.3.x still
imports at module load time. Importing this module applies small aliases and
no-op type stubs so the voice engine can initialize. Must be imported before
any module that imports pytgcalls.
"""

import logging

logger = logging.getLogger(__name__)


class _InputGroupCallSlugShim:
    """Stand-in for the removed pyrogram.raw.types.InputGroupCallSlug.

    Only used by py-tgcalls on slug-based call updates / phone-call migration,
    which never occur in normal group voice streaming.
    """

    def __init__(self, *args, **kwargs):
        self.slug = kwargs.get("slug")
        self.id = None
        self.access_hash = None


class _MigrateConferenceCallReasonShim:
    """Stand-in for the removed PhoneCallDiscardReasonMigrateConferenceCall."""

    def __init__(self, *args, **kwargs):
        self.slug = kwargs.get("slug")


def apply_patches() -> None:
    import pyrogram.errors
    import pyrogram.raw.types

    if not hasattr(pyrogram.errors, "GroupcallForbidden"):
        setattr(
            pyrogram.errors,
            "GroupcallForbidden",
            getattr(pyrogram.errors, "BroadcastForbidden", pyrogram.errors.Forbidden),
        )

    if not hasattr(pyrogram.errors, "GroupcallInvalid"):
        setattr(
            pyrogram.errors,
            "GroupcallInvalid",
            getattr(pyrogram.errors, "GroupCallInvalid", pyrogram.errors.BadRequest),
        )

    if not hasattr(pyrogram.raw.types, "InputGroupCallSlug"):
        setattr(pyrogram.raw.types, "InputGroupCallSlug", _InputGroupCallSlugShim)

    if not hasattr(pyrogram.raw.types, "PhoneCallDiscardReasonMigrateConferenceCall"):
        setattr(
            pyrogram.raw.types,
            "PhoneCallDiscardReasonMigrateConferenceCall",
            _MigrateConferenceCallReasonShim,
        )

    logger.debug("py-tgcalls compatibility patches applied")


apply_patches()
