"""add negative antigen cols

Revision ID: 2321b5cbc876
Revises: db050f46440f
Create Date: 2020-08-28 15:30:53.840491

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2321b5cbc876'
down_revision = 'db050f46440f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('coreData', sa.Column('negativeTestsAntigen', sa.Integer(), nullable=True))
    op.add_column('coreData', sa.Column('negativeTestsPeopleAntigen', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('coreData', 'negativeTestsPeopleAntigen')
    op.drop_column('coreData', 'negativeTestsAntigen')
    # ### end Alembic commands ###
