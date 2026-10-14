import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from utils.timeutil import as_utc
from database import SessionLocal, OAuthTransaction
from utils.security import token_hash, encrypt_secret, decrypt_secret

TRANSACTION_MINUTES = 10

def utcnow():
    return datetime.now(timezone.utc)

def store_transaction(provider, state, payload, link_user_id=None):
    with SessionLocal() as db:
        db.add(OAuthTransaction(
            state_hash=token_hash(state), provider=provider,
            encrypted_payload=encrypt_secret(json.dumps(payload)),
            link_user_id=link_user_id,
            expires_at=utcnow() + timedelta(minutes=TRANSACTION_MINUTES),
        ))
        db.commit()

def consume_transaction(provider, state):
    now = utcnow()
    with SessionLocal() as db:
        row = db.scalar(select(OAuthTransaction).where(
            OAuthTransaction.provider == provider,
            OAuthTransaction.state_hash == token_hash(state),
            OAuthTransaction.consumed_at.is_(None),
        ))
        if not row or as_utc(row.expires_at) <= now:
            return None
        row.consumed_at = now
        payload = json.loads(decrypt_secret(row.encrypted_payload))
        result = {'payload': payload, 'link_user_id': row.link_user_id}
        db.commit()
        return result
