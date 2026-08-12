"""Allow ``python -m sync_kit`` as an alternative to the ``bos-sync`` script."""

from __future__ import annotations

from .cli import main

raise SystemExit(main())
