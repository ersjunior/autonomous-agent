"""add_lead_base_and_campaign_channels

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-06-03 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_bases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("data_recebimento", sa.Date(), nullable=False),
        sa.Column("data_inicio", sa.Date(), nullable=True),
        sa.Column("data_fim", sa.Date(), nullable=True),
        sa.Column("column_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lead_bases_campaign_id"), "lead_bases", ["campaign_id"], unique=False)

    op.create_table(
        "campaign_channels",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "channel_type"),
    )

    # Migra channel_type único da campanha para a tabela associativa N:N.
    op.execute(
        """
        INSERT INTO campaign_channels (campaign_id, channel_type)
        SELECT id, LOWER(channel_type::text)
        FROM campaigns
        """
    )
    op.drop_column("campaigns", "channel_type")

    op.create_table(
        "lead_base_channels",
        sa.Column("lead_base_id", sa.UUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["lead_base_id"], ["lead_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("lead_base_id", "channel_type"),
    )

    # Leads antigos não possuem lead_base_id; schema anterior é incompatível.
    op.execute("DELETE FROM leads")

    op.drop_column("leads", "name")
    op.drop_column("leads", "phone")
    op.drop_column("leads", "email")
    op.drop_column("leads", "extra_data")
    op.drop_column("leads", "status")

    op.add_column("leads", sa.Column("lead_base_id", sa.UUID(), nullable=False))
    op.add_column("leads", sa.Column("id_cliente", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("nome_cliente", sa.String(length=255), nullable=False))
    op.add_column("leads", sa.Column("cpf_cliente", sa.String(length=14), nullable=True))
    op.add_column("leads", sa.Column("email_cliente", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("telefone_1", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("telefone_2", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("telefone_3", sa.String(length=50), nullable=True))
    op.add_column(
        "leads",
        sa.Column("aux_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )

    op.create_foreign_key(
        "fk_leads_lead_base_id",
        "leads",
        "lead_bases",
        ["lead_base_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_leads_lead_base_id"), "leads", ["lead_base_id"], unique=False)

    op.alter_column("leads", "aux_values", server_default=None)

    op.execute("CREATE INDEX idx_lead_aux_values ON leads USING gin (aux_values)")


def downgrade() -> None:
    op.drop_index("idx_lead_aux_values", table_name="leads")
    op.drop_index(op.f("ix_leads_lead_base_id"), table_name="leads")
    op.drop_constraint("fk_leads_lead_base_id", "leads", type_="foreignkey")

    op.add_column("leads", sa.Column("status", sa.String(length=50), nullable=False, server_default="new"))
    op.add_column(
        "leads",
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )
    op.add_column("leads", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("name", sa.String(length=255), nullable=False, server_default=""))

    op.drop_column("leads", "aux_values")
    op.drop_column("leads", "telefone_3")
    op.drop_column("leads", "telefone_2")
    op.drop_column("leads", "telefone_1")
    op.drop_column("leads", "email_cliente")
    op.drop_column("leads", "cpf_cliente")
    op.drop_column("leads", "nome_cliente")
    op.drop_column("leads", "id_cliente")
    op.drop_column("leads", "lead_base_id")

    op.alter_column("leads", "status", server_default=None)
    op.alter_column("leads", "extra_data", server_default=None)
    op.alter_column("leads", "name", server_default=None)

    op.drop_table("lead_base_channels")

    channel_type_col = postgresql.ENUM(
        "WHATSAPP", "TELEGRAM", "VOICE", "VIDEO", name="channel_type", create_type=False
    )
    op.add_column(
        "campaigns",
        sa.Column("channel_type", channel_type_col, nullable=True),
    )
    op.execute(
        """
        UPDATE campaigns c
        SET channel_type = UPPER(cc.channel_type)::channel_type
        FROM (
            SELECT DISTINCT ON (campaign_id) campaign_id, channel_type
            FROM campaign_channels
            ORDER BY campaign_id, channel_type
        ) cc
        WHERE c.id = cc.campaign_id
        """
    )
    op.alter_column("campaigns", "channel_type", nullable=False)
    op.drop_table("campaign_channels")

    op.drop_index(op.f("ix_lead_bases_campaign_id"), table_name="lead_bases")
    op.drop_table("lead_bases")
