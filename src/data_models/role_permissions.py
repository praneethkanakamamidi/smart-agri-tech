from sqlalchemy import Column, Integer, ForeignKey, TIMESTAMP, Index
from src.db_connections.postgresql_conn import Base

class RolePermissions(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("idx_role_permissions_role", "role_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey('roles.id', ondelete='CASCADE'))
    permission_id = Column(Integer, ForeignKey('permissions.id', ondelete='CASCADE'))
    can_read = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    can_write = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    can_delete = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
