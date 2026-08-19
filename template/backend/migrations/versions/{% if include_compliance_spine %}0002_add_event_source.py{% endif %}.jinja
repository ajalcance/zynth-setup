"""add events.source (server vs client-reported)

Separate revision rather than an edit to 0001: a project generated before this existed has
already applied 0001, so folding the column in would leave its database silently behind.

Revision ID: 0002source
Revises: 0001spine
Create Date: client-telemetry boundary
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002source"
down_revision: str | Sequence[str] | None = "0001spine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision's schema changes."""
    # server_default, not just default: existing rows predate client reporting, and every one of
    # them was observed by this service. NOT NULL from the start — a null source is a row whose
    # trust level is unknown, and the audit filter would then have to guess.
    op.add_column(
        "events",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="server"),
    )
    op.create_index("ix_events_source_action", "events", ["source", "action"])


def downgrade() -> None:
    """Revert this revision's schema changes."""
    op.drop_index("ix_events_source_action", table_name="events")
    op.drop_column("events", "source")
