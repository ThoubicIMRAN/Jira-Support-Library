from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, event, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from config import DATABASE_URL

def utcnow(): return datetime.now(timezone.utc)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True); username:Mapped[str]=mapped_column(String(120),unique=True,index=True)
    email:Mapped[str|None]=mapped_column(String(255),unique=True,nullable=True,index=True); full_name:Mapped[str]=mapped_column(String(180))
    designation:Mapped[str]=mapped_column(String(180),default='Support Engineer'); password_hash:Mapped[str|None]=mapped_column(String(255),nullable=True)
    role:Mapped[str]=mapped_column(String(30),default='user'); avatar_url:Mapped[str|None]=mapped_column(String(500),nullable=True)
    is_active:Mapped[bool]=mapped_column(Boolean,default=True); must_change_password:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow); last_login:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    designations:Mapped[list['UserProjectDesignation']]=relationship(back_populates='user',cascade='all, delete-orphan')
class Project(Base):
    __tablename__='projects'
    id:Mapped[int]=mapped_column(primary_key=True); key:Mapped[str]=mapped_column(String(80),unique=True,index=True); name:Mapped[str]=mapped_column(String(180))
    description:Mapped[str]=mapped_column(Text,default=''); icon:Mapped[str]=mapped_column(String(20),default='📁'); color:Mapped[str]=mapped_column(String(20),default='#3b82f6')
    sort_order:Mapped[int]=mapped_column(Integer,default=0); is_deleted:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
    categories:Mapped[list['Category']]=relationship(back_populates='project',cascade='all, delete-orphan',order_by='Category.sort_order')
class Category(Base):
    __tablename__='categories'; __table_args__=(UniqueConstraint('project_id','name'),)
    id:Mapped[int]=mapped_column(primary_key=True); project_id:Mapped[int]=mapped_column(ForeignKey('projects.id',ondelete='CASCADE'))
    name:Mapped[str]=mapped_column(String(180)); sort_order:Mapped[int]=mapped_column(Integer,default=0); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    project:Mapped[Project]=relationship(back_populates='categories'); responses:Mapped[list['Response']]=relationship(back_populates='category',cascade='all, delete-orphan',order_by='Response.sort_order')
class Response(Base):
    __tablename__='responses'
    id:Mapped[str]=mapped_column(String(80),primary_key=True); category_id:Mapped[int]=mapped_column(ForeignKey('categories.id',ondelete='CASCADE'))
    title:Mapped[str]=mapped_column(String(240)); badge:Mapped[str|None]=mapped_column(String(40),nullable=True); preview:Mapped[str|None]=mapped_column(Text,nullable=True)
    response_body:Mapped[str]=mapped_column(Text); sort_order:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
    category:Mapped[Category]=relationship(back_populates='responses')
class UserProjectDesignation(Base):
    __tablename__='user_project_designations'; __table_args__=(UniqueConstraint('user_id','project_id'),)
    id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE')); project_id:Mapped[int]=mapped_column(ForeignKey('projects.id',ondelete='CASCADE')); designation:Mapped[str]=mapped_column(String(180))
    user:Mapped[User]=relationship(back_populates='designations'); project:Mapped[Project]=relationship()
class SMTPConfig(Base):
    __tablename__='smtp_config'; id:Mapped[int]=mapped_column(primary_key=True); host:Mapped[str]=mapped_column(String(255)); port:Mapped[int]=mapped_column(Integer,default=587)
    username:Mapped[str]=mapped_column(String(255),default=''); encrypted_password:Mapped[str]=mapped_column(Text,default=''); sender_email:Mapped[str]=mapped_column(String(255)); sender_name:Mapped[str]=mapped_column(String(180),default='Jira Support Library'); use_tls:Mapped[bool]=mapped_column(Boolean,default=True); use_ssl:Mapped[bool]=mapped_column(Boolean,default=False); is_active:Mapped[bool]=mapped_column(Boolean,default=True)
class AuditLog(Base):
    __tablename__='audit_logs'; id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True); action:Mapped[str]=mapped_column(String(80)); entity_type:Mapped[str]=mapped_column(String(80)); entity_id:Mapped[str|None]=mapped_column(String(100),nullable=True); details:Mapped[str|None]=mapped_column(Text,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
engine=create_engine(DATABASE_URL,connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {},pool_pre_ping=True)
if DATABASE_URL.startswith('sqlite'):
 @event.listens_for(engine,'connect')
 def _fk(dbapi_connection,connection_record): dbapi_connection.execute('PRAGMA foreign_keys=ON')
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False)

class PasswordResetToken(Base):
    __tablename__='password_reset_tokens'
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    token_hash:Mapped[str]=mapped_column(String(128),unique=True,index=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    used_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class UserInvitation(Base):
    __tablename__='user_invitations'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(255),index=True)
    role:Mapped[str]=mapped_column(String(30),default='user')
    designation:Mapped[str]=mapped_column(String(180),default='Support Engineer')
    token_hash:Mapped[str]=mapped_column(String(128),unique=True,index=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    accepted_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    invited_by:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)


class UserAuthIdentity(Base):
    __tablename__='user_auth_identities'
    __table_args__=(UniqueConstraint('provider','provider_subject'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    provider:Mapped[str]=mapped_column(String(30),index=True)
    provider_subject:Mapped[str]=mapped_column(String(255),index=True)
    provider_email:Mapped[str|None]=mapped_column(String(255),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    last_used_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    user:Mapped[User]=relationship()


class LoginAttempt(Base):
    __tablename__='login_attempts'
    id:Mapped[int]=mapped_column(primary_key=True)
    identity:Mapped[str]=mapped_column(String(255),index=True)
    succeeded:Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    attempted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)

class AppSession(Base):
    __tablename__='app_sessions'
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    token_hash:Mapped[str]=mapped_column(String(128),unique=True,index=True)
    auth_method:Mapped[str]=mapped_column(String(40),default='local')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    last_seen_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)

class OAuthTransaction(Base):
    __tablename__='oauth_transactions'
    id:Mapped[int]=mapped_column(primary_key=True)
    state_hash:Mapped[str]=mapped_column(String(128),unique=True,index=True)
    provider:Mapped[str]=mapped_column(String(30),index=True)
    encrypted_payload:Mapped[str]=mapped_column(Text)
    link_user_id:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    consumed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)


class UserPreference(Base):
    __tablename__='user_preferences'
    __table_args__=(UniqueConstraint('user_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),unique=True,index=True)
    theme:Mapped[str]=mapped_column(String(20),default='system')
    accent_color:Mapped[str]=mapped_column(String(20),default='#0c46ce')
    font_family:Mapped[str]=mapped_column(String(50),default='DM Sans')
    font_scale:Mapped[int]=mapped_column(Integer,default=100)
    code_font_size:Mapped[int]=mapped_column(Integer,default=12)
    line_height:Mapped[int]=mapped_column(Integer,default=160)
    density:Mapped[str]=mapped_column(String(20),default='comfortable')
    card_columns:Mapped[int]=mapped_column(Integer,default=3)
    border_radius:Mapped[int]=mapped_column(Integer,default=8)
    reduce_motion:Mapped[bool]=mapped_column(Boolean,default=False)
    high_contrast:Mapped[bool]=mapped_column(Boolean,default=False)
    compact_sidebar:Mapped[bool]=mapped_column(Boolean,default=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)


class UserFavorite(Base):
    __tablename__='user_favorites'
    __table_args__=(UniqueConstraint('user_id','response_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    response_id:Mapped[str]=mapped_column(ForeignKey('responses.id',ondelete='CASCADE'),index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class UserPinnedProject(Base):
    __tablename__='user_pinned_projects'
    __table_args__=(UniqueConstraint('user_id','project_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    project_id:Mapped[int]=mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class UserRecentResponse(Base):
    __tablename__='user_recent_responses'
    __table_args__=(UniqueConstraint('user_id','response_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    response_id:Mapped[str]=mapped_column(ForeignKey('responses.id',ondelete='CASCADE'),index=True)
    viewed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)
    view_count:Mapped[int]=mapped_column(Integer,default=1)

class ResponseUsageEvent(Base):
    __tablename__='response_usage_events'
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True,index=True)
    response_id:Mapped[str]=mapped_column(ForeignKey('responses.id',ondelete='CASCADE'),index=True)
    action:Mapped[str]=mapped_column(String(30),index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)


class UserSavedSearch(Base):
    __tablename__='user_saved_searches'
    __table_args__=(UniqueConstraint('user_id','name'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    name:Mapped[str]=mapped_column(String(120))
    query:Mapped[str]=mapped_column(String(500),default='')
    project_id:Mapped[int|None]=mapped_column(ForeignKey('projects.id',ondelete='SET NULL'),nullable=True)
    category_id:Mapped[int|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True)
    tag:Mapped[str|None]=mapped_column(String(80),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ResponseTag(Base):
    __tablename__='response_tags'
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(80),unique=True,index=True)
    color:Mapped[str]=mapped_column(String(20),default='#0c46ce')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ResponseTagLink(Base):
    __tablename__='response_tag_links'
    __table_args__=(UniqueConstraint('response_id','tag_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    response_id:Mapped[str]=mapped_column(ForeignKey('responses.id',ondelete='CASCADE'),index=True)
    tag_id:Mapped[int]=mapped_column(ForeignKey('response_tags.id',ondelete='CASCADE'),index=True)


class UserNotificationState(Base):
    __tablename__='user_notification_states'
    __table_args__=(UniqueConstraint('user_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),unique=True,index=True)
    last_seen_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)
    notify_new_responses:Mapped[bool]=mapped_column(Boolean,default=True)
    notify_updated_responses:Mapped[bool]=mapped_column(Boolean,default=True)




class ResponseEmbedding(Base):
    """Vector fingerprint of a response for local similarity search."""
    __tablename__ = 'response_embeddings'
    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[str] = mapped_column(
        ForeignKey('responses.id', ondelete='CASCADE'), unique=True, index=True
    )
    embedding_json: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(80), default='nomic-embed-text')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIGenerationLog(Base):
    """Audit trail for AI reuse vs generate decisions."""
    __tablename__ = 'ai_generation_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(40), index=True)
    source_text_hash: Mapped[str] = mapped_column(String(64), index=True)
    matched_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


def init_db(): Base.metadata.create_all(engine)


# --- Jira integration ---
class UserJiraCredential(Base):
    __tablename__ = 'user_jira_credentials'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), unique=True, index=True)
    product: Mapped[str] = mapped_column(String(20), default='cloud')
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ProjectJiraLink(Base):
    __tablename__ = 'project_jira_links'
    __table_args__ = (UniqueConstraint('project_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    jira_project_key: Mapped[str] = mapped_column(String(40), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class JiraTransitionAlias(Base):
    __tablename__ = 'jira_transition_aliases'
    __table_args__ = (UniqueConstraint('jira_project_key', 'raw_name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    jira_project_key: Mapped[str] = mapped_column(String(40), default='*', index=True)
    raw_name: Mapped[str] = mapped_column(String(120))
    friendly_label: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# --- AI approval workflow ---
class AiPendingResponse(Base):
    """AI-generated text waiting for manager/admin approval before library save."""
    __tablename__ = 'ai_pending_responses'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('categories.id', ondelete='SET NULL'), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default='AI generated response')
    body: Mapped[str] = mapped_column(Text)
    ticket_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending|approved|rejected
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class UserConfluenceCredential(Base):
    """Per-user Confluence access (resolution notes). Optional; can mirror Jira token."""
    __tablename__ = "user_confluence_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_jira_credentials: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeatureFeedback(Base):
    __tablename__ = "feature_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(40), default="improvement")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class UserProjectAccess(Base):
    __tablename__ = "user_project_access"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)


class BulkPostLog(Base):
    """One row per bulk Jira comment run (who, which tickets, what succeeded)."""
    __tablename__ = 'bulk_post_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    jira_prefix: Mapped[str] = mapped_column(String(40), index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    ok_keys: Mapped[str] = mapped_column(Text, default='')
    failed_json: Mapped[str] = mapped_column(Text, default='[]')
    body_preview: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
