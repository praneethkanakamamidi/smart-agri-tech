from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, TIMESTAMP, Boolean, Index, func, text
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base

# Trust levels (users.verification_status)
UNVERIFIED = "UNVERIFIED"
PENDING_VERIFICATION = "PENDING_VERIFICATION"
VERIFIED = "VERIFIED"
REJECTED = "REJECTED"
SUSPENDED = "SUSPENDED"


class Users(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_email", func.lower(text("email")), unique=True, postgresql_where=text("email IS NOT NULL")),
        Index("uq_users_phone", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True)
    user_name = Column(String(120))  # Login identifier: email or mobile number
    first_name = Column(String(30))
    last_name = Column(String(30))
    password = Column(String(150))
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    role_id = Column(Integer, ForeignKey('roles.id', ondelete='CASCADE'))
    state = Column(Integer, ForeignKey('states.id', ondelete='CASCADE'))
    district = Column(Integer, ForeignKey('districts.id', ondelete='CASCADE'))
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))

    email = Column(String(120), nullable=True)
    phone = Column(String(20), nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    phone_verified = Column(Boolean, default=False, nullable=False)
    preferred_language = Column(String(5), default="en", nullable=False)
    verification_status = Column(String(30), default=UNVERIFIED, nullable=False)
    suspended_reason = Column(String(255), nullable=True)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted = Column(String(255), nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    deletion_requested_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    role_rel = relationship("Roles", foreign_keys=[role_id], lazy="raise")
    status_rel = relationship("Miscellaneous_Data", foreign_keys=[status], lazy="raise")
    state_rel = relationship("States", foreign_keys=[state], lazy="raise")
    district_rel = relationship("Districts", foreign_keys=[district], lazy="raise")
