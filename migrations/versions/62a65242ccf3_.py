"""empty message

Revision ID: 62a65242ccf3
Revises: 2c216b8ce1b5
Create Date: 2020-06-11 19:15:40.412891

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '62a65242ccf3'
down_revision = '2c216b8ce1b5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('coreData', 'lastUpdateTime',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('coreData', 'lastUpdateTime',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False)
    # ### end Alembic commands ###
