"""add text risk columns to anomaly_inferences

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # score/features pasan a nullable: quedan NULL cuando el texto rechaza y el
    # Isolation Forest no llega a ejecutarse (cortocircuito).
    op.alter_column("anomaly_inferences", "score", existing_type=sa.Float(), nullable=True)
    op.alter_column(
        "anomaly_inferences", "features", existing_type=postgresql.JSONB(), nullable=True
    )
    # Nuevas columnas del análisis de texto.
    op.add_column(
        "anomaly_inferences",
        sa.Column(
            "text_is_fraud",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "anomaly_inferences", sa.Column("text_reasons", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "anomaly_inferences",
        sa.Column("anomaly_source", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("anomaly_inferences", "anomaly_source")
    op.drop_column("anomaly_inferences", "text_reasons")
    op.drop_column("anomaly_inferences", "text_is_fraud")
    op.alter_column(
        "anomaly_inferences", "features", existing_type=postgresql.JSONB(), nullable=False
    )
    op.alter_column("anomaly_inferences", "score", existing_type=sa.Float(), nullable=False)
