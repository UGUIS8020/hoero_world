"""empty message

Revision ID: fc04b8d043b4
Revises: 38d01777e319
Create Date: 2024-01-29 22:51:57.643167

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fc04b8d043b4'
down_revision = '38d01777e319'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('blog_post',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('date', sa.DateTime(), nullable=True),
    sa.Column('title', sa.String(length=140), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('summary', sa.String(length=140), nullable=True),
    sa.Column('featured_image', sa.String(length=140), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('administrator', sa.String(length=1), nullable=True))
        batch_op.drop_column('adminisrator')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('adminisrator', sa.VARCHAR(length=1), nullable=True))
        batch_op.drop_column('administrator')

    op.drop_table('blog_post')
    # ### end Alembic commands ###
