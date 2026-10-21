from alembic import op

revision = '0002_safety'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    from backend.safety.models import Incident, Action
    Incident.__table__.create(op.get_bind(), checkfirst=True)
    Action.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table('safety_actions')
    op.drop_table('safety_events')
