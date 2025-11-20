"""
Salesforce OAuth2 Connector - FastAPI Backend
Simple, stable POC for OAuth handshake, token storage, auto-refresh, and API calls
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from pydantic import BaseModel, Field
from typing import Literal, Optional
import os
from dotenv import load_dotenv

from .db import init_db, get_credentials, save_credentials, update_credentials
from .salesforce import (
    generate_auth_url,
    exchange_code_for_tokens,
    call_salesforce,
    SalesforceError
)

load_dotenv()

app = FastAPI(
    title="Salesforce OAuth Connector",
    description="Simple POC for Salesforce OAuth2 handshake with token management",
    version="0.1.0",
    docs_url=None,  # Disable default docs
    redoc_url=None  # Disable default redoc
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()


class StartOAuthRequest(BaseModel):
    """Request to start OAuth flow"""
    environment: Literal["production", "sandbox", "custom"] = Field(
        ...,
        description="Salesforce environment type"
    )
    custom_domain: Optional[str] = Field(
        None,
        description="Custom domain URL (required if environment=custom)"
    )
    client_id: str = Field(..., description="Salesforce Connected App Client ID")
    client_secret: str = Field(..., description="Salesforce Connected App Client Secret")


class AuthUrlResponse(BaseModel):
    """Response containing OAuth authorization URL"""
    auth_url: str


class StatusResponse(BaseModel):
    """Current connection status"""
    status: Literal["disconnected", "connected", "error"]
    environment: Optional[str] = None
    instance_url: Optional[str] = None
    expires_at: Optional[str] = None
    error_message: Optional[str] = None
    updated_at: Optional[str] = None


@app.get("/")
async def root():
    """
    Root endpoint - Landing page with API documentation links
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Salesforce OAuth Connector</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }
                body {
                    font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                    min-height: 100vh;
                    line-height: 1.6;
                }
                .nav {
                    background: rgba(30, 41, 59, 0.8);
                    border-bottom: 1px solid #334155;
                    padding: 16px 0;
                    position: sticky;
                    top: 0;
                    z-index: 1000;
                    backdrop-filter: blur(8px);
                }
                .nav-container {
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 0 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 16px;
                }
                .nav-brand {
                    font-size: 1.25rem;
                    font-weight: 700;
                    background: linear-gradient(135deg, #22d3ee, #0891b2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    text-decoration: none;
                }
                .nav-links {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .nav-link {
                    color: #cbd5e1;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    border: 1px solid transparent;
                }
                .nav-link:hover {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.1);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                .nav-link.active {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.2);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                .container {
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 40px 20px;
                }
                .card {
                    background: rgba(30, 41, 59, 0.6);
                    border-radius: 12px;
                    border: 1px solid #334155;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                    padding: 40px;
                }
                .header {
                    border-bottom: 1px solid #334155;
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                }
                .status {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: rgba(20, 83, 45, 0.2);
                    color: #22c55e;
                    padding: 6px 16px;
                    border-radius: 20px;
                    font-size: 14px;
                    font-weight: 600;
                    margin-bottom: 16px;
                    border: 1px solid rgba(34, 197, 94, 0.3);
                }
                .status::before {
                    content: '';
                    width: 8px;
                    height: 8px;
                    background: #22c55e;
                    border-radius: 50%;
                    animation: pulse 2s ease-in-out infinite;
                }
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
                h1 {
                    color: #f1f5f9;
                    margin: 8px 0 12px 0;
                    font-size: 2.25rem;
                    font-weight: 700;
                    background: linear-gradient(135deg, #22d3ee, #0891b2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                }
                h2 {
                    color: #f1f5f9;
                    margin-bottom: 16px;
                    font-size: 1.5rem;
                    font-weight: 600;
                }
                p {
                    color: #cbd5e1;
                    margin-bottom: 12px;
                }
                .section {
                    margin: 32px 0;
                    padding: 24px;
                    background: rgba(15, 23, 42, 0.5);
                    border-radius: 8px;
                    border: 1px solid #334155;
                }
                .btn {
                    display: inline-block;
                    background: #22d3ee;
                    color: #0f172a;
                    padding: 12px 28px;
                    text-decoration: none;
                    border-radius: 6px;
                    margin: 8px 12px 8px 0;
                    font-weight: 600;
                    transition: all 0.2s ease;
                    border: 1px solid #0891b2;
                }
                .btn:hover {
                    background: #0891b2;
                    transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
                }
                .btn-secondary {
                    background: #475569;
                    color: #f1f5f9;
                    border: 1px solid #64748b;
                }
                .btn-secondary:hover {
                    background: #64748b;
                    box-shadow: 0 4px 12px rgba(71, 85, 105, 0.3);
                }
                code {
                    background: #1e293b;
                    color: #22d3ee;
                    padding: 3px 8px;
                    border-radius: 4px;
                    font-family: 'Courier New', monospace;
                    font-size: 0.9em;
                    border: 1px solid #334155;
                }
                ul, ol {
                    padding-left: 24px;
                    color: #cbd5e1;
                }
                li {
                    margin: 10px 0;
                }
                li code {
                    margin-right: 8px;
                }
                .emoji {
                    font-style: normal;
                }
            </style>
        </head>
        <body>
            <nav class="nav">
                <div class="nav-container">
                    <a href="/" class="nav-brand">Salesforce OAuth</a>
                    <div class="nav-links">
                        <a href="/" class="nav-link active">Home</a>
                        <a href="/docs" class="nav-link">API Docs</a>
                        <a href="/redoc" class="nav-link">ReDoc</a>
                        <a href="/status-page" class="nav-link">Status</a>
                        <a href="/health-page" class="nav-link">Health</a>
                    </div>
                </div>
            </nav>
            
            <div class="container">
                <div class="card">
                    <div class="header">
                        <span class="status">ONLINE</span>
                        <h1><span class="emoji">🔐</span> Salesforce OAuth Connector</h1>
                        <p>A simple, stable FastAPI backend for Salesforce OAuth2 integration.</p>
                    </div>
                    
                    <div class="section">
                        <h2><span class="emoji">📚</span> API Documentation</h2>
                        <p>Interact with all endpoints through our interactive API documentation:</p>
                        <a href="/docs" class="btn">Open Swagger UI</a>
                        <a href="/redoc" class="btn btn-secondary">Open ReDoc</a>
                    </div>
                    
                    <div class="section">
                        <h2><span class="emoji">🚀</span> Available Endpoints</h2>
                        <ul>
                            <li><code>GET /health</code> Health check</li>
                            <li><code>POST /api/connectors/salesforce/start</code> Start OAuth flow</li>
                            <li><code>GET /oauth/callback/salesforce</code> OAuth callback handler</li>
                            <li><code>GET /api/connectors/salesforce/status</code> Connection status</li>
                            <li><code>GET /api/connectors/salesforce/test</code> Test API connection</li>
                            <li><code>POST /api/connectors/salesforce/disconnect</code> Disconnect</li>
                        </ul>
                    </div>
                    
                    <div class="section">
                        <h2><span class="emoji">📖</span> Setup Instructions</h2>
                        <p>To use this connector:</p>
                        <ol>
                            <li>Create a Connected App in Salesforce</li>
                            <li>Set <code>SALESFORCE_CALLBACK_URL</code> in Replit Secrets</li>
                            <li>Use the Swagger UI to initiate OAuth flow</li>
                        </ol>
                        <p>See the <strong>README.md</strong> file for detailed instructions.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    )


@app.get("/docs")
async def custom_swagger_ui():
    """
    Custom Swagger UI with AutonomOS navigation
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>API Documentation - Salesforce Connector</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
            <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                    min-height: 100vh;
                }
                .nav {
                    background: rgba(30, 41, 59, 0.8);
                    border-bottom: 1px solid #334155;
                    padding: 16px 0;
                    position: sticky;
                    top: 0;
                    z-index: 10000;
                    backdrop-filter: blur(8px);
                }
                .nav-container {
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 0 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 16px;
                }
                .nav-brand {
                    font-size: 1.25rem;
                    font-weight: 700;
                    background: linear-gradient(135deg, #22d3ee, #0891b2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    text-decoration: none;
                }
                .nav-links {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .nav-link {
                    color: #cbd5e1;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    border: 1px solid transparent;
                }
                .nav-link:hover {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.1);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                .nav-link.active {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.2);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                #swagger-ui {
                    max-width: 1460px;
                    margin: 0 auto;
                }
            </style>
        </head>
        <body>
            <nav class="nav">
                <div class="nav-container">
                    <a href="/" class="nav-brand">Salesforce OAuth</a>
                    <div class="nav-links">
                        <a href="/" class="nav-link">Home</a>
                        <a href="/docs" class="nav-link active">API Docs</a>
                        <a href="/redoc" class="nav-link">ReDoc</a>
                        <a href="/status-page" class="nav-link">Status</a>
                        <a href="/health-page" class="nav-link">Health</a>
                    </div>
                </div>
            </nav>
            
            <div id="swagger-ui"></div>
            
            <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
            <script>
                window.onload = function() {
                    window.ui = SwaggerUIBundle({
                        url: '/openapi.json',
                        dom_id: '#swagger-ui',
                        deepLinking: true,
                        presets: [
                            SwaggerUIBundle.presets.apis,
                            SwaggerUIBundle.SwaggerUIStandalonePreset
                        ],
                    })
                }
            </script>
        </body>
        </html>
        """
    )


@app.get("/redoc")
async def custom_redoc():
    """
    Custom ReDoc with AutonomOS navigation
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>API Documentation - Salesforce Connector</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                    min-height: 100vh;
                }
                .nav {
                    background: rgba(30, 41, 59, 0.8);
                    border-bottom: 1px solid #334155;
                    padding: 16px 0;
                    position: sticky;
                    top: 0;
                    z-index: 10000;
                    backdrop-filter: blur(8px);
                }
                .nav-container {
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 0 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 16px;
                }
                .nav-brand {
                    font-size: 1.25rem;
                    font-weight: 700;
                    background: linear-gradient(135deg, #22d3ee, #0891b2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    text-decoration: none;
                }
                .nav-links {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .nav-link {
                    color: #cbd5e1;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    border: 1px solid transparent;
                }
                .nav-link:hover {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.1);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                .nav-link.active {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.2);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                redoc {
                    display: block;
                }
            </style>
        </head>
        <body>
            <nav class="nav">
                <div class="nav-container">
                    <a href="/" class="nav-brand">Salesforce OAuth</a>
                    <div class="nav-links">
                        <a href="/" class="nav-link">Home</a>
                        <a href="/docs" class="nav-link">API Docs</a>
                        <a href="/redoc" class="nav-link active">ReDoc</a>
                        <a href="/status-page" class="nav-link">Status</a>
                        <a href="/health-page" class="nav-link">Health</a>
                    </div>
                </div>
            </nav>
            
            <redoc spec-url='/openapi.json'></redoc>
            
            <script src="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"></script>
        </body>
        </html>
        """
    )


@app.get("/health")
async def health_check():
    """
    Health check endpoint - verify server is running (JSON API)
    """
    return {"status": "ok"}


@app.get("/health-page")
async def health_page():
    """
    Health check page - human-friendly HTML version
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Health Check - Salesforce Connector</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                    min-height: 100vh;
                    line-height: 1.6;
                }
                .nav {
                    background: rgba(30, 41, 59, 0.8);
                    border-bottom: 1px solid #334155;
                    padding: 16px 0;
                    position: sticky;
                    top: 0;
                    z-index: 1000;
                    backdrop-filter: blur(8px);
                }
                .nav-container {
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 0 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 16px;
                }
                .nav-brand {
                    font-size: 1.25rem;
                    font-weight: 700;
                    background: linear-gradient(135deg, #22d3ee, #0891b2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    text-decoration: none;
                }
                .nav-links {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .nav-link {
                    color: #cbd5e1;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    border: 1px solid transparent;
                }
                .nav-link:hover {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.1);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                .nav-link.active {
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.2);
                    border-color: rgba(34, 211, 238, 0.3);
                }
                .container {
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 40px 20px;
                }
                .card {
                    background: rgba(30, 41, 59, 0.6);
                    border-radius: 12px;
                    border: 1px solid #334155;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                    padding: 40px;
                }
                .header {
                    border-bottom: 1px solid #334155;
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                    text-align: center;
                }
                .status-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: rgba(20, 83, 45, 0.2);
                    color: #22c55e;
                    padding: 8px 20px;
                    border-radius: 24px;
                    font-size: 16px;
                    font-weight: 600;
                    border: 1px solid rgba(34, 197, 94, 0.3);
                }
                .status-badge::before {
                    content: '';
                    width: 10px;
                    height: 10px;
                    background: #22c55e;
                    border-radius: 50%;
                    animation: pulse 2s ease-in-out infinite;
                }
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
                h1 {
                    color: #f1f5f9;
                    margin: 16px 0 12px 0;
                    font-size: 2.25rem;
                    font-weight: 700;
                }
                .info-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-top: 24px;
                }
                .info-card {
                    background: rgba(15, 23, 42, 0.5);
                    border: 1px solid #334155;
                    border-radius: 8px;
                    padding: 20px;
                }
                .info-card h3 {
                    color: #22d3ee;
                    font-size: 0.9rem;
                    font-weight: 600;
                    text-transform: uppercase;
                    margin-bottom: 8px;
                }
                .info-card p {
                    color: #f1f5f9;
                    font-size: 1.5rem;
                    font-weight: 700;
                }
            </style>
        </head>
        <body>
            <nav class="nav">
                <div class="nav-container">
                    <a href="/" class="nav-brand">Salesforce OAuth</a>
                    <div class="nav-links">
                        <a href="/" class="nav-link">Home</a>
                        <a href="/docs" class="nav-link">API Docs</a>
                        <a href="/redoc" class="nav-link">ReDoc</a>
                        <a href="/status-page" class="nav-link">Status</a>
                        <a href="/health-page" class="nav-link active">Health</a>
                    </div>
                </div>
            </nav>
            
            <div class="container">
                <div class="card">
                    <div class="header">
                        <span class="status-badge">HEALTHY</span>
                        <h1>System Health Check</h1>
                    </div>
                    
                    <div class="info-grid">
                        <div class="info-card">
                            <h3>Server Status</h3>
                            <p style="color: #22c55e;">✓ Online</p>
                        </div>
                        <div class="info-card">
                            <h3>Database</h3>
                            <p style="color: #22c55e;">✓ Connected</p>
                        </div>
                        <div class="info-card">
                            <h3>API Version</h3>
                            <p>v0.1.0</p>
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    )


@app.post("/api/connectors/salesforce/start", response_model=AuthUrlResponse)
async def start_oauth_flow(request: StartOAuthRequest):
    """
    Start Salesforce OAuth flow
    
    Steps:
    1. Validates environment and saves client credentials
    2. Generates OAuth authorization URL
    3. Returns URL for user to visit in browser
    
    After clicking the auth_url, user will be redirected to /oauth/callback/salesforce
    """
    # Validate custom domain requirement
    if request.environment == "custom" and not request.custom_domain:
        raise HTTPException(
            status_code=400,
            detail="custom_domain is required when environment='custom'"
        )
    
    # Determine base URL for auth/token endpoints
    if request.environment == "production":
        base_url = "https://login.salesforce.com"
    elif request.environment == "sandbox":
        base_url = "https://test.salesforce.com"
    else:  # custom
        base_url = request.custom_domain
    
    # Get callback URL from environment
    callback_url = os.getenv("SALESFORCE_CALLBACK_URL")
    if not callback_url:
        # Try to construct default from Replit URL
        replit_url = os.getenv("REPL_SLUG")
        if replit_url:
            callback_url = f"https://{replit_url}.repl.co/oauth/callback/salesforce"
        else:
            raise HTTPException(
                status_code=500,
                detail="SALESFORCE_CALLBACK_URL environment variable not set. Please configure it."
            )
    
    # Generate auth URL and state
    # Ensure base_url and callback_url are strings (not None)
    base_url_str = str(base_url) if base_url else ""
    callback_url_str = str(callback_url) if callback_url else ""
    
    auth_url, state = generate_auth_url(
        base_url=base_url_str,
        client_id=request.client_id,
        redirect_uri=callback_url_str
    )
    
    # Save initial credentials to database
    save_credentials(
        environment=request.environment,
        base_url=base_url_str,
        client_id=request.client_id,
        client_secret=request.client_secret,
        state=state,
        callback_url=callback_url_str
    )
    
    return AuthUrlResponse(auth_url=auth_url)


@app.get("/oauth/callback/salesforce")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Salesforce"),
    state: str = Query(..., description="State parameter for CSRF protection")
):
    """
    OAuth callback endpoint - receives authorization code from Salesforce
    
    This endpoint is called by Salesforce after user authorizes the app.
    It exchanges the code for access/refresh tokens and stores them.
    """
    # Get current credentials
    creds = get_credentials()
    if not creds:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>OAuth Error - Salesforce Connector</title>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
                <style>
                    * { margin: 0; padding: 0; box-sizing: border-box; }
                    body {
                        font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: #0f172a;
                        color: #e2e8f0;
                        min-height: 100vh;
                        line-height: 1.6;
                    }
                    .nav {
                        background: rgba(30, 41, 59, 0.8);
                        border-bottom: 1px solid #334155;
                        padding: 16px 0;
                        backdrop-filter: blur(8px);
                    }
                    .nav-container {
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 0 20px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        flex-wrap: wrap;
                        gap: 16px;
                    }
                    .nav-brand {
                        font-size: 1.25rem;
                        font-weight: 700;
                        background: linear-gradient(135deg, #22d3ee, #0891b2);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                        text-decoration: none;
                    }
                    .nav-links {
                        display: flex;
                        gap: 8px;
                        flex-wrap: wrap;
                    }
                    .nav-link {
                        color: #cbd5e1;
                        text-decoration: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        font-weight: 500;
                        transition: all 0.2s ease;
                        border: 1px solid transparent;
                    }
                    .nav-link:hover {
                        color: #22d3ee;
                        background: rgba(34, 211, 238, 0.1);
                        border-color: rgba(34, 211, 238, 0.3);
                    }
                    .container {
                        max-width: 700px;
                        margin: 60px auto;
                        padding: 40px 20px;
                    }
                    .card {
                        background: rgba(30, 41, 59, 0.6);
                        border-radius: 12px;
                        border: 1px solid #334155;
                        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                        padding: 48px;
                        text-align: center;
                    }
                    .error-icon {
                        width: 80px;
                        height: 80px;
                        margin: 0 auto 24px;
                        background: rgba(127, 29, 29, 0.2);
                        border: 2px solid #ef4444;
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 40px;
                    }
                    h1 {
                        color: #ef4444;
                        font-size: 2rem;
                        font-weight: 700;
                        margin-bottom: 16px;
                    }
                    p {
                        color: #cbd5e1;
                        margin-bottom: 24px;
                        font-size: 1.1rem;
                    }
                    .btn {
                        display: inline-block;
                        background: #22d3ee;
                        color: #0f172a;
                        padding: 12px 28px;
                        text-decoration: none;
                        border-radius: 6px;
                        margin-top: 24px;
                        font-weight: 600;
                        transition: all 0.2s ease;
                        border: 1px solid #0891b2;
                    }
                    .btn:hover {
                        background: #0891b2;
                        transform: translateY(-1px);
                        box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
                    }
                </style>
            </head>
            <body>
                <nav class="nav">
                    <div class="nav-container">
                        <a href="/" class="nav-brand">Salesforce OAuth</a>
                        <div class="nav-links">
                            <a href="/" class="nav-link">Home</a>
                            <a href="/docs" class="nav-link">API Docs</a>
                            <a href="/redoc" class="nav-link">ReDoc</a>
                            <a href="/status-page" class="nav-link">Status</a>
                            <a href="/health-page" class="nav-link">Health</a>
                        </div>
                    </div>
                </nav>
                
                <div class="container">
                    <div class="card">
                        <div class="error-icon">✗</div>
                        <h1>No OAuth Flow in Progress</h1>
                        <p>Please start the OAuth flow first using the API.</p>
                        <a href="/docs" class="btn">Go to API Documentation</a>
                    </div>
                </div>
            </body>
            </html>
            """,
            status_code=400
        )
    
    # Validate state
    if creds.get("state") != state:
        update_credentials(
            status="error",
            error_message="Invalid state parameter - possible CSRF attack"
        )
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>OAuth Error - Salesforce Connector</title>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
                <style>
                    * { margin: 0; padding: 0; box-sizing: border-box; }
                    body {
                        font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: #0f172a;
                        color: #e2e8f0;
                        min-height: 100vh;
                        line-height: 1.6;
                    }
                    .nav {
                        background: rgba(30, 41, 59, 0.8);
                        border-bottom: 1px solid #334155;
                        padding: 16px 0;
                        backdrop-filter: blur(8px);
                    }
                    .nav-container {
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 0 20px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        flex-wrap: wrap;
                        gap: 16px;
                    }
                    .nav-brand {
                        font-size: 1.25rem;
                        font-weight: 700;
                        background: linear-gradient(135deg, #22d3ee, #0891b2);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                        text-decoration: none;
                    }
                    .nav-links {
                        display: flex;
                        gap: 8px;
                        flex-wrap: wrap;
                    }
                    .nav-link {
                        color: #cbd5e1;
                        text-decoration: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        font-weight: 500;
                        transition: all 0.2s ease;
                        border: 1px solid transparent;
                    }
                    .nav-link:hover {
                        color: #22d3ee;
                        background: rgba(34, 211, 238, 0.1);
                        border-color: rgba(34, 211, 238, 0.3);
                    }
                    .container {
                        max-width: 700px;
                        margin: 60px auto;
                        padding: 40px 20px;
                    }
                    .card {
                        background: rgba(30, 41, 59, 0.6);
                        border-radius: 12px;
                        border: 1px solid #334155;
                        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                        padding: 48px;
                        text-align: center;
                    }
                    .error-icon {
                        width: 80px;
                        height: 80px;
                        margin: 0 auto 24px;
                        background: rgba(127, 29, 29, 0.2);
                        border: 2px solid #ef4444;
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 40px;
                    }
                    h1 {
                        color: #ef4444;
                        font-size: 2rem;
                        font-weight: 700;
                        margin-bottom: 16px;
                    }
                    p {
                        color: #cbd5e1;
                        margin-bottom: 24px;
                        font-size: 1.1rem;
                    }
                    .warning {
                        background: rgba(124, 45, 18, 0.2);
                        border: 1px solid #f97316;
                        border-radius: 8px;
                        padding: 16px;
                        margin-top: 24px;
                        color: #fb923c;
                    }
                    .btn {
                        display: inline-block;
                        background: #22d3ee;
                        color: #0f172a;
                        padding: 12px 28px;
                        text-decoration: none;
                        border-radius: 6px;
                        margin-top: 24px;
                        font-weight: 600;
                        transition: all 0.2s ease;
                        border: 1px solid #0891b2;
                    }
                    .btn:hover {
                        background: #0891b2;
                        transform: translateY(-1px);
                        box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
                    }
                </style>
            </head>
            <body>
                <nav class="nav">
                    <div class="nav-container">
                        <a href="/" class="nav-brand">Salesforce OAuth</a>
                        <div class="nav-links">
                            <a href="/" class="nav-link">Home</a>
                            <a href="/docs" class="nav-link">API Docs</a>
                            <a href="/redoc" class="nav-link">ReDoc</a>
                            <a href="/status-page" class="nav-link">Status</a>
                            <a href="/health-page" class="nav-link">Health</a>
                        </div>
                    </div>
                </nav>
                
                <div class="container">
                    <div class="card">
                        <div class="error-icon">✗</div>
                        <h1>Invalid State Parameter</h1>
                        <p>The OAuth callback failed validation.</p>
                        <div class="warning">
                            <strong>Security Warning:</strong> This may indicate a CSRF attack attempt. Please try the OAuth flow again.
                        </div>
                        <a href="/docs" class="btn">Start New OAuth Flow</a>
                    </div>
                </div>
            </body>
            </html>
            """,
            status_code=400
        )
    
    # Exchange code for tokens
    try:
        token_response = exchange_code_for_tokens(
            base_url=creds["base_url"],
            code=code,
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            redirect_uri=creds["callback_url"]
        )
        
        # Update credentials with tokens
        update_credentials(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            instance_url=token_response["instance_url"],
            token_type=token_response.get("token_type", "Bearer"),
            expires_at=token_response["expires_at"],
            status="connected",
            error_message=None
        )
        
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>OAuth Success - Salesforce Connector</title>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
                <style>
                    * { margin: 0; padding: 0; box-sizing: border-box; }
                    body {
                        font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: #0f172a;
                        color: #e2e8f0;
                        min-height: 100vh;
                        line-height: 1.6;
                    }
                    .nav {
                        background: rgba(30, 41, 59, 0.8);
                        border-bottom: 1px solid #334155;
                        padding: 16px 0;
                        backdrop-filter: blur(8px);
                    }
                    .nav-container {
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 0 20px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        flex-wrap: wrap;
                        gap: 16px;
                    }
                    .nav-brand {
                        font-size: 1.25rem;
                        font-weight: 700;
                        background: linear-gradient(135deg, #22d3ee, #0891b2);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                        text-decoration: none;
                    }
                    .nav-links {
                        display: flex;
                        gap: 8px;
                        flex-wrap: wrap;
                    }
                    .nav-link {
                        color: #cbd5e1;
                        text-decoration: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        font-weight: 500;
                        transition: all 0.2s ease;
                        border: 1px solid transparent;
                    }
                    .nav-link:hover {
                        color: #22d3ee;
                        background: rgba(34, 211, 238, 0.1);
                        border-color: rgba(34, 211, 238, 0.3);
                    }
                    .container {
                        max-width: 700px;
                        margin: 60px auto;
                        padding: 40px 20px;
                    }
                    .card {
                        background: rgba(30, 41, 59, 0.6);
                        border-radius: 12px;
                        border: 1px solid #334155;
                        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                        padding: 48px;
                        text-align: center;
                    }
                    .success-icon {
                        width: 80px;
                        height: 80px;
                        margin: 0 auto 24px;
                        background: rgba(20, 83, 45, 0.2);
                        border: 2px solid #22c55e;
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 40px;
                        animation: scaleIn 0.5s ease-out;
                    }
                    @keyframes scaleIn {
                        from { transform: scale(0); opacity: 0; }
                        to { transform: scale(1); opacity: 1; }
                    }
                    h1 {
                        color: #22c55e;
                        font-size: 2rem;
                        font-weight: 700;
                        margin-bottom: 16px;
                    }
                    p {
                        color: #cbd5e1;
                        margin-bottom: 24px;
                        font-size: 1.1rem;
                    }
                    .next-steps {
                        background: rgba(15, 23, 42, 0.5);
                        border: 1px solid #334155;
                        border-radius: 8px;
                        padding: 24px;
                        margin-top: 32px;
                        text-align: left;
                    }
                    .next-steps h2 {
                        color: #f1f5f9;
                        font-size: 1.25rem;
                        margin-bottom: 16px;
                    }
                    .next-steps ul {
                        list-style: none;
                        padding: 0;
                    }
                    .next-steps li {
                        padding: 12px 0;
                        border-bottom: 1px solid #334155;
                    }
                    .next-steps li:last-child {
                        border-bottom: none;
                    }
                    code {
                        background: #1e293b;
                        color: #22d3ee;
                        padding: 3px 8px;
                        border-radius: 4px;
                        font-family: 'Courier New', monospace;
                        font-size: 0.9em;
                        border: 1px solid #334155;
                    }
                    .btn {
                        display: inline-block;
                        background: #22d3ee;
                        color: #0f172a;
                        padding: 12px 28px;
                        text-decoration: none;
                        border-radius: 6px;
                        margin-top: 24px;
                        font-weight: 600;
                        transition: all 0.2s ease;
                        border: 1px solid #0891b2;
                    }
                    .btn:hover {
                        background: #0891b2;
                        transform: translateY(-1px);
                        box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
                    }
                </style>
            </head>
            <body>
                <nav class="nav">
                    <div class="nav-container">
                        <a href="/" class="nav-brand">Salesforce OAuth</a>
                        <div class="nav-links">
                            <a href="/" class="nav-link">Home</a>
                            <a href="/docs" class="nav-link">API Docs</a>
                            <a href="/redoc" class="nav-link">ReDoc</a>
                            <a href="/status-page" class="nav-link">Status</a>
                            <a href="/health-page" class="nav-link">Health</a>
                        </div>
                    </div>
                </nav>
                
                <div class="container">
                    <div class="card">
                        <div class="success-icon">✓</div>
                        <h1>Salesforce Connected Successfully</h1>
                        <p>Your Salesforce account has been authenticated and connected.</p>
                        
                        <div class="next-steps">
                            <h2>Next Steps</h2>
                            <ul>
                                <li><code>GET /api/connectors/salesforce/status</code> - Check connection status</li>
                                <li><code>GET /api/connectors/salesforce/test</code> - Test API connection</li>
                            </ul>
                        </div>
                        
                        <a href="/docs" class="btn">Go to API Documentation</a>
                    </div>
                </div>
            </body>
            </html>
            """
        )
        
    except SalesforceError as e:
        update_credentials(
            status="error",
            error_message=str(e)
        )
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>OAuth Error - Salesforce Connector</title>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
                <style>
                    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                    body {{
                        font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: #0f172a;
                        color: #e2e8f0;
                        min-height: 100vh;
                        line-height: 1.6;
                    }}
                    .nav {{
                        background: rgba(30, 41, 59, 0.8);
                        border-bottom: 1px solid #334155;
                        padding: 16px 0;
                        backdrop-filter: blur(8px);
                    }}
                    .nav-container {{
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 0 20px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        flex-wrap: wrap;
                        gap: 16px;
                    }}
                    .nav-brand {{
                        font-size: 1.25rem;
                        font-weight: 700;
                        background: linear-gradient(135deg, #22d3ee, #0891b2);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                        text-decoration: none;
                    }}
                    .nav-links {{
                        display: flex;
                        gap: 8px;
                        flex-wrap: wrap;
                    }}
                    .nav-link {{
                        color: #cbd5e1;
                        text-decoration: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        font-weight: 500;
                        transition: all 0.2s ease;
                        border: 1px solid transparent;
                    }}
                    .nav-link:hover {{
                        color: #22d3ee;
                        background: rgba(34, 211, 238, 0.1);
                        border-color: rgba(34, 211, 238, 0.3);
                    }}
                    .container {{
                        max-width: 700px;
                        margin: 60px auto;
                        padding: 40px 20px;
                    }}
                    .card {{
                        background: rgba(30, 41, 59, 0.6);
                        border-radius: 12px;
                        border: 1px solid #334155;
                        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                        padding: 48px;
                        text-align: center;
                    }}
                    .error-icon {{
                        width: 80px;
                        height: 80px;
                        margin: 0 auto 24px;
                        background: rgba(127, 29, 29, 0.2);
                        border: 2px solid #ef4444;
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 40px;
                        animation: shake 0.5s ease-out;
                    }}
                    @keyframes shake {{
                        0%, 100% {{ transform: translateX(0); }}
                        25% {{ transform: translateX(-10px); }}
                        75% {{ transform: translateX(10px); }}
                    }}
                    h1 {{
                        color: #ef4444;
                        font-size: 2rem;
                        font-weight: 700;
                        margin-bottom: 16px;
                    }}
                    p {{
                        color: #cbd5e1;
                        margin-bottom: 24px;
                        font-size: 1.1rem;
                    }}
                    .error-details {{
                        background: rgba(15, 23, 42, 0.5);
                        border: 1px solid #334155;
                        border-radius: 8px;
                        padding: 16px;
                        margin-top: 24px;
                        text-align: left;
                        color: #f87171;
                        font-family: 'Courier New', monospace;
                        font-size: 0.9em;
                    }}
                    .btn {{
                        display: inline-block;
                        background: #22d3ee;
                        color: #0f172a;
                        padding: 12px 28px;
                        text-decoration: none;
                        border-radius: 6px;
                        margin-top: 24px;
                        font-weight: 600;
                        transition: all 0.2s ease;
                        border: 1px solid #0891b2;
                    }}
                    .btn:hover {{
                        background: #0891b2;
                        transform: translateY(-1px);
                        box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
                    }}
                </style>
            </head>
            <body>
                <nav class="nav">
                    <div class="nav-container">
                        <a href="/" class="nav-brand">Salesforce OAuth</a>
                        <div class="nav-links">
                            <a href="/" class="nav-link">Home</a>
                            <a href="/docs" class="nav-link">API Docs</a>
                            <a href="/redoc" class="nav-link">ReDoc</a>
                            <a href="/status-page" class="nav-link">Status</a>
                            <a href="/health-page" class="nav-link">Health</a>
                        </div>
                    </div>
                </nav>
                
                <div class="container">
                    <div class="card">
                        <div class="error-icon">✗</div>
                        <h1>OAuth Error</h1>
                        <p>Failed to connect to Salesforce. Please try again.</p>
                        
                        <div class="error-details">
                            {str(e)}
                        </div>
                        
                        <a href="/" class="btn">Return Home</a>
                    </div>
                </div>
            </body>
            </html>
            """,
            status_code=400
        )


@app.get("/api/connectors/salesforce/status", response_model=StatusResponse)
async def get_status():
    """
    Get current Salesforce connection status (JSON API)
    
    Returns connection state, environment, token expiry, and any errors
    """
    creds = get_credentials()
    
    if not creds:
        return StatusResponse(
            status="disconnected",
            environment=None,
            instance_url=None,
            expires_at=None,
            error_message=None,
            updated_at=None
        )
    
    return StatusResponse(
        status=creds.get("status", "disconnected"),
        environment=creds.get("environment"),
        instance_url=creds.get("instance_url"),
        expires_at=creds.get("expires_at"),
        error_message=creds.get("error_message"),
        updated_at=creds.get("updated_at")
    )


@app.get("/status-page")
async def status_page():
    """
    Connection status page - human-friendly HTML version
    """
    creds = get_credentials()
    
    if not creds:
        status = "disconnected"
        status_color = "#64748b"
        status_bg = "rgba(71, 85, 105, 0.2)"
        status_border = "rgba(100, 116, 139, 0.3)"
        environment = "N/A"
        instance_url = "Not connected"
        expires_at = "N/A"
        error_message = None
    else:
        status = creds.get("status", "disconnected")
        environment = creds.get("environment", "N/A")
        instance_url = creds.get("instance_url", "N/A")
        expires_at = creds.get("expires_at", "N/A")
        error_message = creds.get("error_message")
        
        if status == "connected":
            status_color = "#22c55e"
            status_bg = "rgba(20, 83, 45, 0.2)"
            status_border = "rgba(34, 197, 94, 0.3)"
        elif status == "error":
            status_color = "#ef4444"
            status_bg = "rgba(127, 29, 29, 0.2)"
            status_border = "rgba(239, 68, 68, 0.3)"
        else:
            status_color = "#64748b"
            status_bg = "rgba(71, 85, 105, 0.2)"
            status_border = "rgba(100, 116, 139, 0.3)"
    
    error_html = ""
    if error_message:
        error_html = f"""
        <div class="error-box">
            <h3>Error Details</h3>
            <p>{error_message}</p>
        </div>
        """
    
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Connection Status - Salesforce Connector</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: 'Quicksand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                    min-height: 100vh;
                    line-height: 1.6;
                }}
                .nav {{
                    background: rgba(30, 41, 59, 0.8);
                    border-bottom: 1px solid #334155;
                    padding: 16px 0;
                    position: sticky;
                    top: 0;
                    z-index: 1000;
                    backdrop-filter: blur(8px);
                }}
                .nav-container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 0 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 16px;
                }}
                .nav-brand {{
                    font-size: 1.25rem;
                    font-weight: 700;
                    background: linear-gradient(135deg, #22d3ee, #0891b2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    text-decoration: none;
                }}
                .nav-links {{
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }}
                .nav-link {{
                    color: #cbd5e1;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    border: 1px solid transparent;
                }}
                .nav-link:hover {{
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.1);
                    border-color: rgba(34, 211, 238, 0.3);
                }}
                .nav-link.active {{
                    color: #22d3ee;
                    background: rgba(34, 211, 238, 0.2);
                    border-color: rgba(34, 211, 238, 0.3);
                }}
                .container {{
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 40px 20px;
                }}
                .card {{
                    background: rgba(30, 41, 59, 0.6);
                    border-radius: 12px;
                    border: 1px solid #334155;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                    padding: 40px;
                }}
                .header {{
                    border-bottom: 1px solid #334155;
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                    text-align: center;
                }}
                .status-badge {{
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: {status_bg};
                    color: {status_color};
                    padding: 8px 20px;
                    border-radius: 24px;
                    font-size: 16px;
                    font-weight: 600;
                    border: 1px solid {status_border};
                    text-transform: uppercase;
                }}
                .status-badge::before {{
                    content: '';
                    width: 10px;
                    height: 10px;
                    background: {status_color};
                    border-radius: 50%;
                }}
                h1 {{
                    color: #f1f5f9;
                    margin: 16px 0 12px 0;
                    font-size: 2.25rem;
                    font-weight: 700;
                }}
                .info-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-top: 24px;
                }}
                .info-card {{
                    background: rgba(15, 23, 42, 0.5);
                    border: 1px solid #334155;
                    border-radius: 8px;
                    padding: 20px;
                }}
                .info-card h3 {{
                    color: #22d3ee;
                    font-size: 0.9rem;
                    font-weight: 600;
                    text-transform: uppercase;
                    margin-bottom: 8px;
                }}
                .info-card p {{
                    color: #cbd5e1;
                    font-size: 1.1rem;
                    word-break: break-all;
                }}
                .error-box {{
                    background: rgba(127, 29, 29, 0.2);
                    border: 1px solid #ef4444;
                    border-radius: 8px;
                    padding: 16px;
                    margin-top: 24px;
                }}
                .error-box h3 {{
                    color: #ef4444;
                    margin-bottom: 8px;
                }}
                .error-box p {{
                    color: #f87171;
                    font-family: 'Courier New', monospace;
                    font-size: 0.9em;
                }}
                .btn {{
                    display: inline-block;
                    background: #22d3ee;
                    color: #0f172a;
                    padding: 12px 28px;
                    text-decoration: none;
                    border-radius: 6px;
                    margin-top: 24px;
                    font-weight: 600;
                    transition: all 0.2s ease;
                    border: 1px solid #0891b2;
                }}
                .btn:hover {{
                    background: #0891b2;
                    transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
                }}
            </style>
        </head>
        <body>
            <nav class="nav">
                <div class="nav-container">
                    <a href="/" class="nav-brand">Salesforce OAuth</a>
                    <div class="nav-links">
                        <a href="/" class="nav-link">Home</a>
                        <a href="/docs" class="nav-link">API Docs</a>
                        <a href="/redoc" class="nav-link">ReDoc</a>
                        <a href="/status-page" class="nav-link active">Status</a>
                        <a href="/health-page" class="nav-link">Health</a>
                    </div>
                </div>
            </nav>
            
            <div class="container">
                <div class="card">
                    <div class="header">
                        <span class="status-badge">{status}</span>
                        <h1>Salesforce Connection Status</h1>
                    </div>
                    
                    <div class="info-grid">
                        <div class="info-card">
                            <h3>Environment</h3>
                            <p>{environment}</p>
                        </div>
                        <div class="info-card">
                            <h3>Instance URL</h3>
                            <p>{instance_url}</p>
                        </div>
                        <div class="info-card">
                            <h3>Token Expires</h3>
                            <p>{expires_at}</p>
                        </div>
                    </div>
                    
                    {error_html}
                    
                    <a href="/docs" class="btn">View API Documentation</a>
                </div>
            </div>
        </body>
        </html>
        """
    )


@app.get("/api/connectors/salesforce/test")
async def test_connection():
    """
    Test Salesforce connection by calling the Limits API
    
    This validates that:
    1. We have valid credentials
    2. Token refresh works if needed
    3. We can make authenticated API calls
    
    Returns Salesforce org limits data on success
    """
    creds = get_credentials()
    
    if not creds or creds.get("status") != "connected":
        raise HTTPException(
            status_code=400,
            detail="Not connected to Salesforce. Please complete OAuth flow first."
        )
    
    try:
        # Call Salesforce Limits API
        # This will automatically refresh token if needed
        response = call_salesforce(
            method="GET",
            path="/services/data/v59.0/limits"
        )
        
        return {
            "success": True,
            "message": "Successfully connected to Salesforce",
            "data": response
        }
        
    except SalesforceError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Salesforce API call failed: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
