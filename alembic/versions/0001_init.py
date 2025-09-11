from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_init'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('appraisals',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('year', sa.Integer, index=True),
        sa.Column('make', sa.String(100), index=True),
        sa.Column('model', sa.String(100), index=True),
        sa.Column('trim', sa.String(100), nullable=True, index=True),
        sa.Column('benchmark_price', sa.Integer, nullable=False),
        sa.Column('avg_mileage', sa.Integer, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True)
    )

    op.create_table('listings',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('vin', sa.String(32), unique=True, nullable=False),
        sa.Column('year', sa.Integer, index=True),
        sa.Column('make', sa.String(100), index=True),
        sa.Column('model', sa.String(100), index=True),
        sa.Column('trim', sa.String(100), nullable=True, index=True),
        sa.Column('price', sa.Integer, nullable=False),
        sa.Column('mileage', sa.Integer, nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('seller_type', sa.String(50), nullable=True),
        sa.Column('seller', sa.String(200), nullable=True),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('lat', sa.Float, nullable=True),
        sa.Column('lon', sa.Float, nullable=True),
        sa.Column('zip', sa.String(10), nullable=True),
        sa.Column('source', sa.String(100), nullable=False, server_default='apify_autotrader'),
        sa.Column('raw', postgresql.JSON(), nullable=True),
        sa.Column('ingested_at', sa.DateTime, nullable=True)
    )

    op.create_table('matches',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('listing_id', sa.Integer, sa.ForeignKey('listings.id', ondelete='CASCADE')),
        sa.Column('appraisal_id', sa.Integer, sa.ForeignKey('appraisals.id', ondelete='SET NULL'), nullable=True),
        sa.Column('match_level', sa.String(8), nullable=False),
        sa.Column('match_confidence', sa.Integer, nullable=False, server_default='0'),
        sa.Column('shipping_miles', sa.Float, nullable=True),
        sa.Column('shipping_cost', sa.Integer, nullable=True),
        sa.Column('recon_cost', sa.Integer, nullable=True),
        sa.Column('pack_cost', sa.Integer, nullable=True),
        sa.Column('total_cost', sa.Integer, nullable=True),
        sa.Column('gross_margin_dollars', sa.Integer, nullable=True),
        sa.Column('margin_percent', sa.Float, nullable=True),
        sa.Column('category', sa.String(12), nullable=False, server_default='SKIP'),
        sa.Column('explanations', postgresql.JSON(), nullable=True),
        sa.Column('scored_at', sa.DateTime, nullable=True)
    )

    op.create_table('settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', postgresql.JSON(), nullable=True)
    )

def downgrade():
    op.drop_table('settings')
    op.drop_table('matches')
    op.drop_table('listings')
    op.drop_table('appraisals')
