"""create anomaly_inferences table

Revision ID: 0001
Revises:
Create Date: 2026-06-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "anomaly_inferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("draft_id", sa.String(length=255), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_anomaly_inferences_draft_id", "anomaly_inferences", ["draft_id"]
    )
    op.create_index(
        "ix_anomaly_inferences_created_at", "anomaly_inferences", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_anomaly_inferences_created_at", table_name="anomaly_inferences")
    op.drop_index("ix_anomaly_inferences_draft_id", table_name="anomaly_inferences")
    op.drop_table("anomaly_inferences")
