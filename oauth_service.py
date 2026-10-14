import secrets
from datetime import datetime, timezone
import msal
import requests
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from database import SessionLocal, User, UserAuthIdentity, AuditLog
from config import (MS_CLIENT_ID,MS_CLIENT_SECRET,MS_TENANT_ID,MS_REDIRECT_URI,
                    GOOGLE_CLIENT_ID,GOOGLE_CLIENT_SECRET,GOOGLE_REDIRECT_URI,OAUTH_AUTO_CREATE)
from services.security_policy import email_allowed,tenant_allowed,mapped_ms_role
from services.oauth_transaction_service import store_transaction,consume_transaction

MS_SCOPES=['openid','profile','email','User.Read']
GOOGLE_SCOPES=['openid','profile','email']

class OAuthError(RuntimeError): pass

def configured(provider):
    if provider=='microsoft': return bool(MS_CLIENT_ID and MS_CLIENT_SECRET and MS_REDIRECT_URI)
    if provider=='google': return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)
    return False

def _ms_app():
    authority=f'https://login.microsoftonline.com/{MS_TENANT_ID}'
    return msal.ConfidentialClientApplication(MS_CLIENT_ID,authority=authority,client_credential=MS_CLIENT_SECRET)

def start_microsoft(session, link_user_id=None):
    if not configured('microsoft'): raise OAuthError('Microsoft OAuth is not configured.')
    flow=_ms_app().initiate_auth_code_flow(scopes=MS_SCOPES,redirect_uri=MS_REDIRECT_URI)
    session['oauth_ms_flow']=flow
    session['oauth_provider']='microsoft'; session['oauth_link_user_id']=link_user_id
    store_transaction('microsoft', flow['state'], flow, link_user_id)
    return flow['auth_uri']

def finish_microsoft(query,session):
    flow=session.pop('oauth_ms_flow',None)
    link_user_id=session.pop('oauth_link_user_id',None)
    if not flow:
        transaction=consume_transaction('microsoft',query.get('state',''))
        if transaction: flow=transaction['payload']; link_user_id=transaction['link_user_id']
    if not flow: raise OAuthError('Microsoft sign-in session expired. Start again.')
    try: result=_ms_app().acquire_token_by_auth_code_flow(flow,dict(query))
    except ValueError as exc: raise OAuthError('Microsoft state validation failed.') from exc
    if 'error' in result: raise OAuthError(result.get('error_description',result['error']))
    claims=result.get('id_token_claims') or {}
    access=result.get('access_token')
    profile={}
    if access:
        response=requests.get('https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName',headers={'Authorization':f'Bearer {access}'},timeout=15)
        if response.ok: profile=response.json()
    subject=str(profile.get('id') or claims.get('oid') or claims.get('sub') or '')
    email=(profile.get('mail') or profile.get('userPrincipalName') or claims.get('preferred_username') or claims.get('email') or '').lower()
    name=profile.get('displayName') or claims.get('name') or email.split('@')[0]
    if not subject: raise OAuthError('Microsoft did not return a stable account identifier.')
    if not tenant_allowed(claims.get('tid')): raise OAuthError('This Microsoft tenant is not allowed.')
    if not email_allowed(email): raise OAuthError('This email domain is not allowed.')
    return complete_sign_in('microsoft',subject,email,name,None,link_user_id,mapped_ms_role(claims.get('roles',[])))

def _google_flow():
    config={'web':{'client_id':GOOGLE_CLIENT_ID,'client_secret':GOOGLE_CLIENT_SECRET,
                   'auth_uri':'https://accounts.google.com/o/oauth2/auth',
                   'token_uri':'https://oauth2.googleapis.com/token',
                   'redirect_uris':[GOOGLE_REDIRECT_URI]}}
    return Flow.from_client_config(config,scopes=GOOGLE_SCOPES,redirect_uri=GOOGLE_REDIRECT_URI)

def start_google(session, link_user_id=None):
    if not configured('google'): raise OAuthError('Google OAuth is not configured.')
    flow=_google_flow(); nonce=secrets.token_urlsafe(32)
    url,state=flow.authorization_url(access_type='online',include_granted_scopes='true',prompt='select_account',nonce=nonce)
    session['oauth_google_state']=state; session['oauth_google_nonce']=nonce; session['oauth_provider']='google'; session['oauth_link_user_id']=link_user_id
    store_transaction('google',state,{'nonce':nonce},link_user_id)
    return url

def finish_google(query,session):
    expected=session.pop('oauth_google_state',None); nonce=session.pop('oauth_google_nonce',None); link_user_id=session.pop('oauth_link_user_id',None)
    if not expected:
        transaction=consume_transaction('google',query.get('state',''))
        if transaction: expected=query.get('state'); nonce=transaction['payload']['nonce']; link_user_id=transaction['link_user_id']
    if not expected or query.get('state')!=expected: raise OAuthError('Google state validation failed.')
    if query.get('error'): raise OAuthError(query.get('error_description',query['error']))
    flow=_google_flow()
    try: flow.fetch_token(code=query.get('code'))
    except Exception as exc: raise OAuthError('Google authorization code exchange failed.') from exc
    try: claims=id_token.verify_oauth2_token(flow.credentials.id_token,google_requests.Request(),GOOGLE_CLIENT_ID)
    except Exception as exc: raise OAuthError('Google ID token validation failed.') from exc
    if claims.get('nonce')!=nonce: raise OAuthError('Google nonce validation failed.')
    if not claims.get('email_verified'): raise OAuthError('Google email address is not verified.')
    if not email_allowed(claims.get('email','')): raise OAuthError('This email domain is not allowed.')
    return complete_sign_in('google',str(claims['sub']),claims.get('email','').lower(),claims.get('name') or claims.get('email','User'),claims.get('picture'),link_user_id)

def complete_sign_in(provider,subject,email,full_name,avatar_url,link_user_id=None,provisioned_role='user'):
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        identity=db.scalar(select(UserAuthIdentity).where(UserAuthIdentity.provider==provider,UserAuthIdentity.provider_subject==subject))
        if identity:
            user=db.get(User,identity.user_id)
            if not user or not user.is_active: raise OAuthError('This account is inactive.')
            identity.last_used_at=now; user.last_login=now
        else:
            if link_user_id:
                user=db.get(User,link_user_id)
                if not user or not user.is_active: raise OAuthError('The account selected for linking is inactive.')
                identity=UserAuthIdentity(user_id=user.id,provider=provider,provider_subject=subject,provider_email=email or None,last_used_at=now)
                db.add(identity)
            else:
                if email and db.scalar(select(User).where(User.email==email)):
                    raise OAuthError('An account already uses this email. Sign in locally and link the provider from Profile.')
                if not OAUTH_AUTO_CREATE: raise OAuthError('Automatic OAuth account creation is disabled.')
                base=(email.split('@')[0] if email else f'{provider}_{subject[:8]}').replace(' ','_')[:100]
                username=base; suffix=1
                while db.scalar(select(User).where(User.username==username)):
                    suffix+=1; username=f'{base}_{suffix}'
                user=User(username=username,email=email or None,full_name=full_name or username,designation='Support Engineer',password_hash=None,role=provisioned_role,avatar_url=avatar_url,is_active=True,must_change_password=False,last_login=now)
                db.add(user); db.flush()
                identity=UserAuthIdentity(user_id=user.id,provider=provider,provider_subject=subject,provider_email=email or None,last_used_at=now)
                db.add(identity)
        db.add(AuditLog(user_id=user.id,action='login',entity_type='user',entity_id=str(user.id),details=f'oauth:{provider}'))
        db.commit(); db.refresh(user); return user
