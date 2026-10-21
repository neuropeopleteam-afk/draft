"""А2 (21.10): честный статус протокола ФСП (protocol_status, protocol_ref, ekp_no, evsk_rank, evsk_basis) и срок действия ключей ATS (90 дней)."""
from alembic import op
import sqlalchemy as sa

revision = "a2_02"
down_revision = "w1_merge"
branch_labels = None
depends_on = None


def _has_col(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_col("fsp_achievements", "protocol_status"):
        op.add_column("fsp_achievements", sa.Column("protocol_status", sa.String(32), nullable=False, server_default="none"))
    if not _has_col("fsp_achievements", "protocol_ref"):
        op.add_column("fsp_achievements", sa.Column("protocol_ref", sa.JSON(), nullable=True))
    if not _has_col("fsp_achievements", "ekp_no"):
        op.add_column("fsp_achievements", sa.Column("ekp_no", sa.String(64), nullable=True))
    if not _has_col("fsp_achievements", "evsk_rank"):
        op.add_column("fsp_achievements", sa.Column("evsk_rank", sa.String(64), nullable=True))
    if not _has_col("fsp_achievements", "evsk_basis"):
        op.add_column("fsp_achievements", sa.Column("evsk_basis", sa.String(255), nullable=True))

    # А8/А2: перенос старых номеров ЕКП, ошибочно записанных в evsk_code, в отдельное поле ekp_no
    if _has_col("fsp_achievements", "ekp_no") and _has_col("fsp_achievements", "evsk_code"):
        op.execute(
            sa.text(
                "UPDATE fsp_achievements SET ekp_no = evsk_code, evsk_code = NULL "
                "WHERE ekp_no IS NULL AND evsk_code IS NOT NULL AND ("
                "source_ref LIKE 'protocol:%' OR evsk_code LIKE '2101%' OR evsk_code LIKE '1101%' "
                "OR evsk_code LIKE '2025%' OR evsk_code LIKE '2026%' OR evsk_code LIKE 'СБОРНАЯ%' "
                "OR evsk_code LIKE 'КР-%' OR evsk_code LIKE 'КФ-%' OR evsk_code LIKE 'ПФО-%' OR evsk_code LIKE 'ЦФО-%')"
            )
        )
        op.execute(
            sa.text(
                "UPDATE fsp_achievements SET evsk_code = NULL "
                "WHERE source_ref LIKE 'protocol:%' AND evsk_code IS NOT NULL"
            )
        )

    if not _has_col("ats_settings", "huntflow_token_expires_at"):
        op.add_column("ats_settings", sa.Column("huntflow_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_col("ats_settings", "webhook_secret_expires_at"):
        op.add_column("ats_settings", sa.Column("webhook_secret_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ats_settings") as b:
        if _has_col("ats_settings", "webhook_secret_expires_at"):
            b.drop_column("webhook_secret_expires_at")
        if _has_col("ats_settings", "huntflow_token_expires_at"):
            b.drop_column("huntflow_token_expires_at")
    with op.batch_alter_table("fsp_achievements") as b:
        for col in ("evsk_basis", "evsk_rank", "ekp_no", "protocol_ref", "protocol_status"):
            if _has_col("fsp_achievements", col):
                b.drop_column(col)
