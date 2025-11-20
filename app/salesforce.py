"""
Salesforce OAuth Client Module
Handles OAuth flow, token refresh, and API calls
"""
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
import secrets
from .db import get_credentials, update_credentials


class SalesforceError(Exception):
    """Custom exception for Salesforce API errors"""
    pass


def generate_auth_url(base_url: str, client_id: str, redirect_uri: str) -> Tuple[str, str]:
    """
    Generate Salesforce OAuth authorization URL
    
    Returns:
        Tuple of (auth_url, state)
    """
    # Generate random state for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Build authorization URL
    auth_endpoint = f"{base_url}/services/oauth2/authorize"
    
    auth_url = (
        f"{auth_endpoint}?"
        f"response_type=code&"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"state={state}"
    )
    
    return auth_url, state


def exchange_code_for_tokens(
    base_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str
) -> Dict[str, Any]:
    """
    Exchange authorization code for access/refresh tokens
    
    Returns:
        Dict with access_token, refresh_token, instance_url, expires_at, etc.
    """
    token_endpoint = f"{base_url}/services/oauth2/token"
    
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri
    }
    
    try:
        response = httpx.post(token_endpoint, data=data, timeout=30.0)
        response.raise_for_status()
        
        token_data = response.json()
        
        # Calculate expires_at (Salesforce tokens typically expire in 2 hours)
        # If expires_in is provided, use it; otherwise default to 60 minutes
        expires_in = token_data.get("issued_at", 3600)  # Default 1 hour
        if isinstance(expires_in, str):
            expires_in = 3600
        
        # Subtract 5 minute safety margin
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)
        
        return {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "instance_url": token_data["instance_url"],
            "token_type": token_data.get("token_type", "Bearer"),
            "expires_at": expires_at.isoformat()
        }
        
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text
        raise SalesforceError(f"Token exchange failed: {error_detail}")
    except Exception as e:
        raise SalesforceError(f"Token exchange error: {str(e)}")


def refresh_salesforce_token() -> bool:
    """
    Refresh access token using refresh token
    
    Returns:
        True if refresh successful, False otherwise
    """
    creds = get_credentials()
    if not creds or not creds.get("refresh_token"):
        return False
    
    token_endpoint = f"{creds['base_url']}/services/oauth2/token"
    
    data = {
        "grant_type": "refresh_token",
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"]
    }
    
    try:
        response = httpx.post(token_endpoint, data=data, timeout=30.0)
        response.raise_for_status()
        
        token_data = response.json()
        
        # Calculate new expiry
        expires_at = datetime.utcnow() + timedelta(hours=1, minutes=55)  # 1h 55m (5 min margin)
        
        # Update credentials with new token
        update_credentials(
            access_token=token_data["access_token"],
            instance_url=token_data.get("instance_url", creds["instance_url"]),
            token_type=token_data.get("token_type", "Bearer"),
            expires_at=expires_at.isoformat(),
            status="connected",
            error_message=None
        )
        
        return True
        
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text
        update_credentials(
            status="error",
            error_message=f"Token refresh failed: {error_detail}"
        )
        return False
    except Exception as e:
        update_credentials(
            status="error",
            error_message=f"Token refresh error: {str(e)}"
        )
        return False


def call_salesforce(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Make authenticated API call to Salesforce
    
    Automatically refreshes token if expired or near expiry
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., /services/data/v59.0/limits)
        params: Query parameters
        json_body: JSON request body
    
    Returns:
        Response data as dict
    """
    creds = get_credentials()
    if not creds or creds.get("status") != "connected":
        raise SalesforceError("Not connected to Salesforce")
    
    # Check if token needs refresh
    if creds.get("expires_at"):
        expires_at = datetime.fromisoformat(creds["expires_at"])
        now = datetime.utcnow()
        
        # Refresh if expired or expiring within 1 minute
        if expires_at <= now + timedelta(minutes=1):
            if not refresh_salesforce_token():
                raise SalesforceError("Failed to refresh token")
            # Reload credentials after refresh
            creds = get_credentials()
    
    # Build request
    url = f"{creds['instance_url']}{path}"
    headers = {
        "Authorization": f"{creds['token_type']} {creds['access_token']}",
        "Content-Type": "application/json"
    }
    
    try:
        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=30.0
        )
        
        # Handle 401 - try refresh once
        if response.status_code == 401:
            if refresh_salesforce_token():
                # Retry once after refresh
                creds = get_credentials()
                headers["Authorization"] = f"{creds['token_type']} {creds['access_token']}"
                
                response = httpx.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=30.0
                )
            else:
                raise SalesforceError("Authentication failed and token refresh failed")
        
        response.raise_for_status()
        return response.json()
        
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text
        raise SalesforceError(f"API call failed: {error_detail}")
    except Exception as e:
        raise SalesforceError(f"API call error: {str(e)}")
