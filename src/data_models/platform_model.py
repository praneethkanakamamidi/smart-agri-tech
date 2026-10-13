from sqlalchemy import (
    Column, String, Integer, DateTime, Date, ForeignKey, Boolean, JSON, Text, UniqueConstraint, BigInteger, Time,
    Numeric,
)
from src.db_connections.postgresql_conn import Base


class PlatformSettings(Base):
    """Admin-configurable marketplace configuration (fees, expiry defaults, policies). Versioned."""
    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(60), unique=True, nullable=False)
    value = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    description = Column(String(255))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    updated_at = Column(DateTime)


class PlatformSettingsHistory(Base):
    __tablename__ = "platform_settings_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(60), nullable=False)
    value = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False)
    changed_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    change_reason = Column(String(255))
    changed_at = Column(DateTime)


class AuditLogs(Base):
    """Append-only security and business event history."""
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)  # null = system
    actor_role = Column(String(20))
    action = Column(String(60), nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(String(40))
    before = Column(JSON)
    after = Column(JSON)
    ip_address = Column(String(64))
    created_at = Column(DateTime)


class IdempotencyKeys(Base):
    """Stored responses for critical writes so retries don't create duplicates."""
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint('user_id', 'endpoint', 'key', name='uq_idempotency_key'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    endpoint = Column(String(120), nullable=False)
    key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status_code = Column(Integer)
    response = Column(JSON)
    created_at = Column(DateTime)


class StoredFiles(Base):
    """Uploaded file metadata. Content lives in the storage backend at storage_path."""
    __tablename__ = "stored_files"

    id = Column(String(36), primary_key=True)  # uuid4
    owner_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    purpose = Column(String(30), nullable=False)
    original_name = Column(String(255))
    content_type = Column(String(60), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_path = Column(String(255), nullable=False)
    created_at = Column(DateTime)
    deleted_at = Column(DateTime)


class UserSessions(Base):
    """One row per logged-in device; refresh tokens carry the session's jti."""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    jti = Column(String(64), unique=True, nullable=False)
    device_name = Column(String(120))
    user_agent = Column(String(255))
    ip_address = Column(String(64))
    created_at = Column(DateTime)
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)


class DeviceTokens(Base):
    """Push notification tokens."""
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token = Column(String(512), unique=True, nullable=False)
    platform = Column(String(20))  # android | ios | web
    created_at = Column(DateTime)
    last_seen_at = Column(DateTime)


class OtpCodes(Base):
    """OTP store used when OTP_STORE=postgres (hashed codes only)."""
    __tablename__ = "otp_codes"
    __table_args__ = (UniqueConstraint('identifier', 'purpose', name='uq_otp_identifier_purpose'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    identifier = Column(String(120), nullable=False)
    purpose = Column(String(30), nullable=False)
    code_hash = Column(String(128), nullable=False)
    attempts_left = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime)


class Reports(Base):
    """User reports of abusive users, listings, reviews or messages."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    target_type = Column(String(20), nullable=False)  # user | listing | review | message
    target_id = Column(Integer, nullable=False)
    reason = Column(String(40), nullable=False)
    details = Column(String(1000))
    status = Column(String(20), nullable=False)  # open | actioned | dismissed
    reviewed_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_notes = Column(String(500))
    created_at = Column(DateTime)
    reviewed_at = Column(DateTime)


class UserBlocks(Base):
    __tablename__ = "user_blocks"
    __table_args__ = (UniqueConstraint('blocker_id', 'blocked_id', name='uq_user_block'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    blocker_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    blocked_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime)


class AccountAppeals(Base):
    __tablename__ = "account_appeals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reason = Column(String(1000), nullable=False)
    status = Column(String(20), nullable=False)  # open | accepted | rejected
    reviewed_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_notes = Column(String(500))
    created_at = Column(DateTime)
    reviewed_at = Column(DateTime)


class Announcements(Base):
    """Platform announcements and promotional campaigns."""
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(150), nullable=False)
    body = Column(Text, nullable=False)
    title_te = Column(String(150))
    body_te = Column(Text)
    audience = Column(String(10), nullable=False)  # all | farmer | vendor
    is_promotional = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    starts_at = Column(DateTime)
    ends_at = Column(DateTime)
    notified_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)


class SupportTickets(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    subject = Column(String(150), nullable=False)
    category = Column(String(30), nullable=False)  # account | payment | order | listing | technical | other
    status = Column(String(20), nullable=False)  # open | in_progress | resolved | closed
    priority = Column(String(10), nullable=False)  # low | normal | high | urgent
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)
    assigned_to = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    closed_at = Column(DateTime)


class SupportTicketMessages(Base):
    __tablename__ = "support_ticket_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey('support_tickets.id', ondelete='CASCADE'), nullable=False)
    author_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    body = Column(Text, nullable=False)
    file_ids = Column(JSON)
    is_internal = Column(Boolean, default=False, nullable=False)  # admin-only note
    created_at = Column(DateTime)


class NotificationPreferences(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    email_enabled = Column(Boolean, default=True, nullable=False)
    sms_enabled = Column(Boolean, default=True, nullable=False)
    push_enabled = Column(Boolean, default=True, nullable=False)
    whatsapp_enabled = Column(Boolean, default=False, nullable=False)
    promotional_enabled = Column(Boolean, default=False, nullable=False)
    quiet_hours_start = Column(Time)
    quiet_hours_end = Column(Time)
    updated_at = Column(DateTime)


class NotificationDeliveries(Base):
    """Outbound delivery attempts for a notification on an external channel."""
    __tablename__ = "notification_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(Integer, ForeignKey('notifications.id', ondelete='CASCADE'), nullable=False)
    channel = Column(String(20), nullable=False)  # email | sms | push | whatsapp
    status = Column(String(20), nullable=False)  # pending | sent | failed | skipped
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(String(255))
    next_attempt_at = Column(DateTime)
    sent_at = Column(DateTime)
    created_at = Column(DateTime)


class RecurringOrders(Base):
    """A recurring supply agreement proposed by a vendor and approved by the farmer."""
    __tablename__ = "recurring_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    frequency = Column(String(10), nullable=False)  # weekly | biweekly | monthly
    next_run_date = Column(Date, nullable=False)
    end_date = Column(Date)
    fulfillment_mode = Column(String(30), nullable=False)
    payment_terms = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)  # proposed | active | paused | cancelled | rejected
    last_order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)
    notes = Column(String(500))
    approved_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
