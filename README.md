# Salesforce OAuth Connector - Simple POC

A **simple, stable** FastAPI backend that proves we can:
- ✅ Do correct OAuth2 handshake with Salesforce
- ✅ Store access/refresh tokens in SQLite
- ✅ Automatically refresh tokens when needed
- ✅ Call Salesforce REST APIs

**No frontend needed** - everything works through FastAPI's built-in Swagger UI at `/docs`.

---

## ▶️ How to Run

**Option 1: Using the start script (Recommended)**
```bash
./start.sh
```

**Option 2: Direct uvicorn command**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

**Option 3: Using run.sh**
```bash
./run.sh
```

The server will start on **http://localhost:5000**

**📚 Once running, open:** http://localhost:5000/docs (Swagger UI)

---

## 🚀 Quick Start (3 Steps)

### Step 1: Set Up Your Callback URL

1. **Start the app** (Replit will auto-run or click the Run button)
2. **Copy your Replit's public URL** - it looks like:
   ```
   https://yourproject.username.repl.co
   ```
3. **Set the callback URL environment variable:**
   - Click the "Secrets" tab (🔒 lock icon) in Replit
   - Add a new secret:
     - Key: `SALESFORCE_CALLBACK_URL`
     - Value: `https://yourproject.username.repl.co/oauth/callback/salesforce`
     - ⚠️ Replace `yourproject.username.repl.co` with your actual Replit URL
     - ⚠️ Don't forget `/oauth/callback/salesforce` at the end!

### Step 2: Configure Salesforce Connected App

You need to create a **Connected App** in Salesforce to get OAuth credentials.

#### In Salesforce:

1. **Go to Setup** → Search for "App Manager"
2. **Click "New Connected App"**
3. **Fill in basic info:**
   - Connected App Name: `My OAuth Connector`
   - Contact Email: your-email@example.com
4. **Enable OAuth Settings:**
   - ✅ Check "Enable OAuth Settings"
   - **Callback URL:** Paste the same URL from Step 1
     ```
     https://yourproject.username.repl.co/oauth/callback/salesforce
     ```
   - **Selected OAuth Scopes:** Add these:
     - `Access and manage your data (api)`
     - `Perform requests on your behalf at any time (refresh_token, offline_access)`
5. **Save** and wait 2-10 minutes for Salesforce to activate it
6. **Copy your credentials:**
   - Click "Manage Consumer Details"
   - Copy **Consumer Key** (this is your `client_id`)
   - Copy **Consumer Secret** (this is your `client_secret`)

### Step 3: Connect to Salesforce

1. **Open Swagger UI** in your browser:
   ```
   https://yourproject.username.repl.co/docs
   ```

2. **Call `POST /api/connectors/salesforce/start`:**
   - Click the endpoint to expand it
   - Click "Try it out"
   - Fill in the request body:
     ```json
     {
       "environment": "production",
       "client_id": "YOUR_CONSUMER_KEY_HERE",
       "client_secret": "YOUR_CONSUMER_SECRET_HERE"
     }
     ```
     - Use `"production"` for real Salesforce orgs
     - Use `"sandbox"` for Salesforce sandbox orgs
     - Use `"custom"` with `"custom_domain"` for custom domains
   
   - Click "Execute"
   - **Copy the `auth_url`** from the response

3. **Authorize in Salesforce:**
   - Paste the `auth_url` into a new browser tab
   - Log in to Salesforce (if not already logged in)
   - Click "Allow" to authorize the app
   - You'll be redirected to a success page

4. **Verify it worked:**
   - Go back to Swagger UI
   - Call `GET /api/connectors/salesforce/status`
   - You should see `"status": "connected"` ✅

---

## 📋 API Endpoints

### 1. `GET /health`
**Purpose:** Check if server is running

**Example Response:**
```json
{
  "status": "ok"
}
```

---

### 2. `POST /api/connectors/salesforce/start`
**Purpose:** Start OAuth flow

**Request Body:**
```json
{
  "environment": "production",
  "client_id": "3MVG9...",
  "client_secret": "ABC123..."
}
```

**Response:**
```json
{
  "auth_url": "https://login.salesforce.com/services/oauth2/authorize?..."
}
```

**What to do next:**
1. Copy the `auth_url`
2. Paste it in a browser
3. Log in and click "Allow"

---

### 3. `GET /oauth/callback/salesforce`
**Purpose:** OAuth callback (Salesforce calls this automatically)

⚠️ **You don't call this manually** - Salesforce redirects here after authorization.

**What it does:**
- Receives the authorization code
- Exchanges it for access/refresh tokens
- Stores tokens in SQLite
- Shows a success page

---

### 4. `GET /api/connectors/salesforce/status`
**Purpose:** Check connection status

**Example Response (Connected):**
```json
{
  "status": "connected",
  "environment": "production",
  "instance_url": "https://myorg.my.salesforce.com",
  "expires_at": "2024-11-20T15:30:00",
  "error_message": null,
  "updated_at": "2024-11-20T13:35:00"
}
```

**Example Response (Disconnected):**
```json
{
  "status": "disconnected",
  "environment": null,
  "instance_url": null,
  "expires_at": null,
  "error_message": null,
  "updated_at": null
}
```

---

### 5. `GET /api/connectors/salesforce/test`
**Purpose:** Test connection by calling Salesforce Limits API

**What it does:**
- Checks if tokens are still valid
- Automatically refreshes if expired
- Makes a real API call to Salesforce
- Returns org limits data

**Example Response:**
```json
{
  "success": true,
  "message": "Successfully connected to Salesforce",
  "data": {
    "DailyApiRequests": {
      "Max": 15000,
      "Remaining": 14950
    },
    "DailyBulkApiRequests": {
      "Max": 5000,
      "Remaining": 5000
    },
    ...
  }
}
```

**If not connected:**
```json
{
  "detail": "Not connected to Salesforce. Please complete OAuth flow first."
}
```

---

## 🔄 How Token Refresh Works

**Automatic refresh happens when:**
1. You call `/api/connectors/salesforce/test`
2. The access token has expired or expires within 1 minute
3. The system tries to refresh using the `refresh_token`
4. If refresh succeeds, new token is saved and API call proceeds
5. If refresh fails, you see an error and need to reconnect

**You don't need to do anything** - it's completely automatic!

---

## 🗄️ Database

Uses **SQLite** (file: `salesforce.db`) with one table:

**Table: `salesforce_credentials`**
- Stores exactly 1 row (for this POC)
- Contains: client_id, client_secret, access_token, refresh_token, etc.

**To reset everything:**
```bash
rm salesforce.db
# Restart the app - database will be recreated empty
```

---

## 🛠️ Troubleshooting

### Problem: "SALESFORCE_CALLBACK_URL not set"
**Solution:** Set the environment variable in Replit Secrets (see Step 1)

### Problem: "Invalid state parameter"
**Solution:** 
- Someone might have tampered with the URL
- Or you restarted the app between starting OAuth and completing it
- Just start over with `POST /start` again

### Problem: "Token refresh failed: invalid_grant"
**Solution:**
- Your refresh token is invalid or revoked
- Disconnect and reconnect by calling `POST /start` again

### Problem: "Not connected to Salesforce"
**Solution:** You need to complete the OAuth flow first (Steps 2-3 in Quick Start)

### Problem: Salesforce redirects to wrong URL
**Solution:**
1. Check your `SALESFORCE_CALLBACK_URL` matches exactly
2. Check your Salesforce Connected App callback URL matches exactly
3. They should both be: `https://yourproject.username.repl.co/oauth/callback/salesforce`

---

## 📁 Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app + all endpoints
│   ├── db.py            # SQLite database operations
│   └── salesforce.py    # OAuth flow + token refresh + API calls
├── .env.example         # Example environment variables
├── README.md            # This file
└── salesforce.db        # SQLite database (created on first run)
```

---

## 🧪 Testing the Complete Flow

Here's the exact sequence to test everything works:

1. **Health check:**
   ```
   GET /health
   → Should return {"status": "ok"}
   ```

2. **Start OAuth:**
   ```
   POST /api/connectors/salesforce/start
   Body: {"environment": "production", "client_id": "...", "client_secret": "..."}
   → Copy auth_url, paste in browser, login, approve
   ```

3. **Check status:**
   ```
   GET /api/connectors/salesforce/status
   → Should show "status": "connected"
   ```

4. **Test API call:**
   ```
   GET /api/connectors/salesforce/test
   → Should return Salesforce limits data
   ```

5. **Test again (to verify token refresh works):**
   - Wait a few minutes or manually expire the token in database
   - Call `/test` again
   - Should automatically refresh and still work

---

## 🎯 What This POC Proves

✅ **OAuth2 handshake works** - Full authorization code flow  
✅ **Token storage works** - Credentials persist in SQLite  
✅ **Auto-refresh works** - Tokens refresh before expiry  
✅ **API calls work** - Can call Salesforce REST endpoints  
✅ **Error handling works** - Clear errors, no crashes  
✅ **Simple to use** - Everything via Swagger UI, no code needed  

---

## 📝 Notes

- This is a **POC** - single org only (one row in database)
- No background jobs or schedulers
- No multi-tenant support
- No credential encryption yet
- Uses FastAPI's built-in docs (Swagger UI) as the interface

**For production**, you'd want to add:
- Multiple org support (multiple rows)
- Encryption for client_secret
- Webhook support
- Rate limiting
- Monitoring/logging
- User authentication

But for proving the OAuth flow works? This is perfect! 🎉
