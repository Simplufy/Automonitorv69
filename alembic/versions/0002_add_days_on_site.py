
"""Add days_on_site column to listings

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    # Add days_on_site column to listings table
    op.add_column('listings', sa.Column('days_on_site', sa.Integer(), nullable=True))

def downgrade():
    # Remove days_on_site column from listings table
    op.drop_column('listings', 'days_on_site')
