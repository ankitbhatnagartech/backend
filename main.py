from fastapi import FastAPI, Body, HTTPException, Depends, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
import os
import logging
import json
from datetime import datetime, timedelta
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import hashlib

from schemas import TrafficInput, ArchitectureType, EstimationResult, ContactSubmission
from estimation_service import EstimationService
from pricing_service import PricingService
from database import Database
from pricing_fetcher import PricingFetcher
from security import verify_admin_token, authenticate_admin
from rate_limiter import limiter, RATE_LIMITS
from email_service import EmailService

# Load environment variables from .env file (for local development)
try:
    from dotenv import load_dotenv
    # Load from parent directory .env (since main.py is in backend/)
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
except ImportError:
    pass # python-dotenv might not be installed in prod

# Setup structured JSON logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Configure root logger
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.root.addHandler(handler)
logging.root.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Scheduler setup
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up ArchCost API...")
    # Optionally skip DB and scheduler startup for local/testing if SKIP_STARTUP_DB=true
    skip_startup = os.getenv("SKIP_STARTUP_DB", "false").lower() == "true"
    
    if not skip_startup:
        # Connect to Database with timeout protection
        try:
            # Set a shorter connection timeout for local dev if default localhost logic applies
            # Motor doesn't block on init, but create_indexes or first query will.
            # We call connect() which is synchronous in the class but assigns client.
            Database.connect()
            
            # Verify connection (server_selection_timeout defaults to 30s which is too long for dev)
            # We can't easily change timeout in connect() without changing Database class signature.
            # But we can try/except the ensure logic.
            
            # Create indexes for optimal performance
            await Database.create_indexes()

            # Load existing dynamic prices
            await PricingService.load_dynamic_prices()

            # Start scheduler
            scheduler.add_job(PricingFetcher.fetch_latest_prices, 'cron', hour=0, minute=0) # Run at midnight
            scheduler.start()
            logger.info("Scheduler started. Price fetch job scheduled for 00:00 daily.")
        except Exception as e:
            logger.error(f"Failed to connect to Database or start scheduler: {e}")
            logger.warning("Continuing app startup without Database. Some features will fail.")
    else:
        logger.info("SKIP_STARTUP_DB=true — skipping Database and scheduler startup for local/testing")

    
    yield
    
    # Shutdown
    try:
        scheduler.shutdown()
    except Exception:
        # Scheduler may not have been started (e.g., SKIP_STARTUP_DB=true)
        logger.info("Scheduler was not running at shutdown; skipping scheduler.shutdown()")
    Database.close()
    logger.info("Scheduler and Database connection shut down.")

app = FastAPI(title="ArchCost API", version="0.1.0", lifespan=lifespan)

# Add GZIP compression middleware for large responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to ArchCost API"}

@app.get("/health")
async def health_check():
    """Health check endpoint for container health monitoring"""
    try:
        # Check database connection
        db = Database.get_db()
        if db is None:
            return {"status": "unhealthy", "reason": "Database not connected"}, 503
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "0.1.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "reason": str(e)}, 503

@app.post("/estimate", response_model=EstimationResult)
@limiter.limit(RATE_LIMITS["estimate"])
async def estimate_cost(
    request: Request,
    payload: dict = Body(...)
):
    """Calculate infrastructure cost based on architecture and traffic"""
    try:
        # Extract parameters from request body
        architecture = payload.get('architecture')
        traffic_dict = payload.get('traffic')
        currency = payload.get('currency', 'USD')
        
        # Validate required fields
        if not architecture or not traffic_dict:
            raise ValueError("Missing required fields: architecture and traffic")
        
        # Convert traffic dict to TrafficInput object
        traffic = TrafficInput(**traffic_dict)

        # Generate comprehensive cache key including ALL traffic parameters BEFORE heavy compute
        # This ensures different inputs produce different cache keys and allows conditional responses
        import json
        cache_key_dict = {
            'architecture': architecture,
            'currency': currency,
            'daily_active_users': traffic.daily_active_users,
            'api_requests_per_user': traffic.api_requests_per_user,
            'storage_per_user_mb': traffic.storage_per_user_mb,
            'peak_traffic_multiplier': traffic.peak_traffic_multiplier,
            'growth_rate_yoy': traffic.growth_rate_yoy,
            'revenue_per_user_monthly': traffic.revenue_per_user_monthly,
            'funding_available': traffic.funding_available,
            'database': traffic.database.model_dump(),
            'cdn': traffic.cdn.model_dump(),
            'messaging': traffic.messaging.model_dump(),
            'security': traffic.security.model_dump(),
            'monitoring': traffic.monitoring.model_dump(),
            'cicd': traffic.cicd.model_dump(),
            'multi_region': traffic.multi_region.model_dump(),
        }
        cache_key = json.dumps(cache_key_dict, sort_keys=True)
        etag = hashlib.md5(cache_key.encode()).hexdigest()

        # If client provided If-None-Match header and it matches, return 304 Not Modified
        client_etag = request.headers.get('if-none-match')
        if client_etag:
            # strip optional quotes
            client_etag_clean = client_etag.strip('"')
            if client_etag_clean == etag:
                logger.info("ETag matches client If-None-Match; returning 304")
                # Return minimal 304 response with ETag so client can reuse cached body
                return Response(status_code=304, headers={
                    'ETag': f'"{etag}"',
                    'Cache-Control': 'no-store',
                    'Vary': 'Accept-Encoding, Content-Type, Accept'
                })

        # Perform estimation (expensive) only when needed
        logger.info(f"Estimating cost for {architecture} with {traffic.daily_active_users} DAU")
        result = EstimationService.estimate(architecture, traffic, currency)
        logger.info(f"Estimation completed successfully. Total cost: {result.monthly_cost.total}")

        # Set response headers for caching and cache-busting
        from fastapi.responses import JSONResponse
        response = JSONResponse(content=result.model_dump())
        # Use no-store to avoid intermediate caches storing potentially stale dynamic results
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["ETag"] = f'"{etag}"'
        response.headers["Vary"] = "Accept-Encoding, Content-Type, Accept"
        response.headers["X-Cache-Key"] = etag

        return response
    except ValueError as ve:
        logger.error(f"Validation error: {ve}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Validation error: {str(ve)}")
        logger.error(f"Error during estimation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error during estimation: {str(e)}")

@app.post("/contact")
@limiter.limit("5/hour")
async def submit_contact_form(
    request: Request,
    submission: ContactSubmission,
    background_tasks: BackgroundTasks = None
):
    """Submit contact form - saves to DB and triggers email"""
    try:
        # Save to Database
        # Save to Database (Best effort, don't fail request if DB is down locally)
        try:
            db = Database.get_db()
            if db is not None:
                doc = submission.model_dump()
                doc["created_at"] = datetime.utcnow().isoformat()
                await db.contact_messages.insert_one(doc)
                logger.info(f"Contact message saved from {submission.email}")
            else:
                logger.warning("Database unavailable, skipping save for contact message.")
        except Exception as db_e:
            logger.error(f"Failed to save contact message to DB: {db_e}")
            # Continue to send email...
        
        # Trigger Email Notification
        # If background_tasks is available (FastAPI dependency), use it. 
        # But we didn't import it in signature yet. Let's send directly via await for now since EmailService puts it in thread.
        await EmailService.send_contact_notification(submission.model_dump())
        
        return {"status": "success", "message": "Message received"}
    except Exception as e:
        logger.error(f"Error submitting contact form: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit message")

@app.get("/admin")
async def admin_portal():
    """Admin portal HTML page - login form"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ArchCost Admin Portal</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
            .container { background: white; padding: 40px; border-radius: 10px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); width: 100%; max-width: 400px; }
            h1 { color: #333; margin-bottom: 30px; text-align: center; font-size: 24px; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 8px; color: #555; font-weight: 500; }
            input { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
            input:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); }
            button { width: 100%; padding: 12px; background: #667eea; color: white; border: none; border-radius: 5px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 10px; }
            button:hover { background: #5568d3; }
            .error { color: #d32f2f; margin-top: 10px; text-align: center; font-size: 13px; display: none; }
            .loading { display: none; text-align: center; color: #667eea; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔐 Admin Portal</h1>
            <form id="loginForm" onsubmit="handleLogin(event)">
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" placeholder="admin" required>
                </div>
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" placeholder="Enter password" required>
                </div>
                <div class="loading" id="loading">Authenticating...</div>
                <div class="error" id="error"></div>
                <button type="submit">Login</button>
            </form>
        </div>
        <script>
            async function handleLogin(e) {
                e.preventDefault();
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const loadingEl = document.getElementById('loading');
                const errorEl = document.getElementById('error');
                
                loadingEl.style.display = 'block';
                errorEl.style.display = 'none';
                
                // Determine API base path
                const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
                const apiBase = isLocal ? '' : '/api';
                
                try {
                    const response = await fetch(`${apiBase}/admin/login`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        localStorage.setItem('admin_token', data.access_token);
                        // Redirect to dashboard UI
                        window.location.href = `${apiBase}/admin/dashboard-ui`;
                    } else {
                        errorEl.textContent = 'Invalid credentials';
                        errorEl.style.display = 'block';
                    }
                } catch (err) {
                    errorEl.textContent = 'Error: ' + err.message;
                    errorEl.style.display = 'block';
                } finally {
                    loadingEl.style.display = 'none';
                }
            }
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

@app.get("/admin/dashboard-ui")
async def admin_dashboard_ui():
    """Admin dashboard UI page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ArchCostEstimator Admin Dashboard</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
            h1 { color: #333; font-size: 28px; }
            .logout-btn { padding: 10px 20px; background: #d32f2f; color: white; border: none; border-radius: 5px; cursor: pointer; }
            .logout-btn:hover { background: #b71c1c; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            .card h2 { color: #667eea; font-size: 16px; margin-bottom: 15px; border-bottom: 1px solid #eee; padding-bottom: 10px; }
            .card-content { font-size: 14px; line-height: 1.6; color: #555; }
            .stat { margin-bottom: 10px; display: flex; justify-content: space-between; }
            .stat-label { color: #999; }
            .stat-value { font-weight: 600; color: #333; }
            .refresh-btn { padding: 10px 20px; background: #4caf50; color: white; border: none; border-radius: 5px; cursor: pointer; margin-top: 15px; width: 100%; }
            .refresh-btn:hover { background: #45a049; }
            .refresh-btn:disabled { background: #ccc; cursor: not-allowed; }
            .status-success { color: #4caf50; font-weight: 600; }
            .status-error { color: #d32f2f; font-weight: 600; }
            .loading { display: none; text-align: center; padding: 20px; }
            .error-message { background: #ffebee; border: 1px solid #ef5350; color: #d32f2f; padding: 15px; border-radius: 5px; margin-bottom: 20px; display: none; }
            .success-message { background: #e8f5e9; border: 1px solid #81c784; color: #2e7d32; padding: 15px; border-radius: 5px; margin-bottom: 20px; display: none; }
            
            /* Messages Table */
            .messages-container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { text-align: left; padding: 12px; border-bottom: 1px solid #eee; font-size: 14px; }
            th { color: #667eea; font-weight: 600; background: #f9f9f9; }
            tr:hover { background: #f5f5f5; }
            .message-date { color: #999; font-size: 12px; white-space: nowrap; }
            .message-subject { font-weight: 500; color: #333; }
            .message-preview { color: #666; max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            .empty-state { text-align: center; padding: 40px; color: #999; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 Admin Dashboard</h1>
                <button class="logout-btn" onclick="logout()">Logout</button>
            </div>
            
            <div class="error-message" id="errorMsg"></div>
            <div class="success-message" id="successMsg"></div>
            
            <div class="grid">
                <div class="card">
                    <h2>💼 Job Status</h2>
                    <div class="card-content">
                        <div class="stat"><span class="stat-label">Status:</span><span class="stat-value" id="jobStatus">Loading...</span></div>
                        <div class="stat"><span class="stat-label">Last Run:</span><span class="stat-value" id="lastRun">Never</span></div>
                        <div class="stat"><span class="stat-label">Success:</span><span class="stat-value" id="jobSuccess">-</span></div>
                        <button class="refresh-btn" onclick="triggerRefresh()">🔄 Refresh Prices Now</button>
                    </div>
                </div>
                
                <div class="card">
                    <h2>📈 Pricing Data</h2>
                    <div class="card-content">
                        <div class="stat"><span class="stat-label">Last Updated:</span><span class="stat-value" id="priceUpdated">Loading...</span></div>
                        <div class="stat"><span class="stat-label">Sources:</span><span class="stat-value" id="priceSources">Loading...</span></div>
                        <div class="stat"><span class="stat-label">Currencies:</span><span class="stat-value" id="priceCurrencies">Loading...</span></div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>📅 Scheduling</h2>
                    <div class="card-content">
                        <div class="stat"><span class="stat-label">Next Run:</span><span class="stat-value" id="nextRun">Loading...</span></div>
                        <div class="stat"><span class="stat-label">Schedule:</span><span class="stat-value" id="schedule">Loading...</span></div>
                        <div class="stat"><span class="stat-label">Time Until:</span><span class="stat-value" id="timeUntil">Loading...</span></div>
                    </div>
                </div>
            </div>

            <!-- Messages Section -->
            <div class="messages-container">
                <h2>📬 Recent Contact Messages</h2>
                <div id="messagesTableContainer">
                    <p class="empty-state">Loading messages...</p>
                </div>
            </div>
        </div>
        
        <script>
            const token = localStorage.getItem('admin_token');
            
            // Determine API base path
            const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
            const apiBase = isLocal ? '' : '/api';

            if (!token) {
                window.location.href = `${apiBase}/admin`;
            }
            
            async function loadDashboard() {
                try {
                    const response = await fetch(`${apiBase}/admin/dashboard`, {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    
                    if (!response.ok) {
                        if (response.status === 401) {
                            window.location.href = `${apiBase}/admin`;
                        }
                        throw new Error('Failed to load dashboard');
                    }
                    
                    const data = await response.json();
                    updateUI(data);
                    
                    // Load messages separately
                    loadMessages();
                } catch (err) {
                    showError('Error loading dashboard: ' + err.message);
                }
            }
            
            async function loadMessages() {
                try {
                    const response = await fetch(`${apiBase}/admin/messages`, {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        renderMessages(data.messages);
                    }
                } catch (err) {
                    console.error('Error loading messages', err);
                }
            }

            function renderMessages(messages) {
                const container = document.getElementById('messagesTableContainer');
                if (!messages || messages.length === 0) {
                    container.innerHTML = '<p class="empty-state">No messages received yet.</p>';
                    return;
                }

                let html = `
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Sender</th>
                                <th>Subject</th>
                                <th>Message</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                messages.forEach(msg => {
                    const date = new Date(msg.created_at).toLocaleString();
                    html += `
                        <tr>
                            <td class="message-date">${date}</td>
                            <td>
                                <strong>${escapeHtml(msg.name)}</strong><br>
                                <span style="color:#666;font-size:12px">${escapeHtml(msg.email)}</span>
                            </td>
                            <td class="message-subject">${escapeHtml(msg.subject)}</td>
                            <td><div class="message-preview" title="${escapeHtml(msg.message)}">${escapeHtml(msg.message)}</div></td>
                        </tr>
                    `;
                });

                html += '</tbody></table>';
                container.innerHTML = html;
            }

            function escapeHtml(text) {
                if (!text) return '';
                return text
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#039;");
            }
            
            function updateUI(data) {
                const job = data.job_status;
                document.getElementById('jobStatus').textContent = job.status;
                document.getElementById('lastRun').textContent = job.last_run || 'Never';
                document.getElementById('jobSuccess').innerHTML = job.success ? '<span class="status-success">✓ Yes</span>' : '<span class="status-error">✗ No</span>';
                
                const pricing = data.current_pricing;
                document.getElementById('priceUpdated').textContent = pricing.last_updated || 'Unknown';
                document.getElementById('priceSources').textContent = pricing.sources.join(', ') || 'None';
                document.getElementById('priceCurrencies').textContent = pricing.total_currencies_configured || 0;
                
                const schedule = data.scheduling;
                document.getElementById('nextRun').textContent = new Date(schedule.next_scheduled_run).toLocaleString();
                document.getElementById('schedule').textContent = schedule.schedule;
                const hours = Math.floor(schedule.time_until_next_run_seconds / 3600);
                const mins = Math.floor((schedule.time_until_next_run_seconds % 3600) / 60);
                document.getElementById('timeUntil').textContent = hours + 'h ' + mins + 'm';
            }
            
            async function triggerRefresh() {
                const btn = event.target;
                btn.disabled = true;
                btn.textContent = '🔄 Refreshing...';
                
                try {
                    const response = await fetch(`${apiBase}/admin/refresh-prices`, {
                        method: 'POST',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    
                    if (response.ok) {
                        showSuccess('Prices refreshed successfully!');
                        setTimeout(() => loadDashboard(), 1000);
                    } else {
                        showError('Failed to refresh prices');
                    }
                } catch (err) {
                    showError('Error: ' + err.message);
                } finally {
                    btn.disabled = false;
                    btn.textContent = '🔄 Refresh Prices Now';
                }
            }
            
            function logout() {
                localStorage.removeItem('admin_token');
                window.location.href = `${apiBase}/admin`;
            }
            
            function showError(msg) {
                const el = document.getElementById('errorMsg');
                el.textContent = msg;
                el.style.display = 'block';
                setTimeout(() => el.style.display = 'none', 5000);
            }
            
            function showSuccess(msg) {
                const el = document.getElementById('successMsg');
                el.textContent = msg;
                el.style.display = 'block';
                setTimeout(() => el.style.display = 'none', 5000);
            }
            
            // Load dashboard on page load and refresh every 30 seconds
            loadDashboard();
            setInterval(loadDashboard, 30000);
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

@app.get("/admin/dashboard")
@limiter.limit(RATE_LIMITS["admin"])
async def admin_dashboard(request: Request, admin: dict = Depends(verify_admin_token)):
    """Admin dashboard - shows pricing job status and last run info"""
    try:
        db = Database.get_db()
        if db is None:
            raise HTTPException(status_code=503, detail="Database not connected")
        
        # Get job status
        job_status = await db.job_status.find_one({"_id": "pricing_job_status"})
        
        # Get current pricing metadata
        current_pricing = await db.pricing.find_one({"_id": "latest_pricing"})
        pricing_meta = current_pricing.get("meta", {}) if current_pricing else {}
        
        # Get history count and details
        history_count = await db.pricing_history.count_documents({})
        history_backups = await db.pricing_history.find(
            {}, 
            sort=[("archived_at", -1)]
        ).to_list(length=2)
        
        # Format history details
        backup_details = []
        for backup in history_backups:
            backup_details.append({
                "archived_at": backup.get("archived_at"),
                "sources": backup.get("meta", {}).get("sources", []),
                "currencies": len(backup.get("currency_rates", {}))
            })
        
        # Calculate next run (daily at 00:00 UTC)
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        next_run = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_until_next = next_run - now
        
        # Parse job status
        job_info = {
            "status": "never_run",
            "last_run": None,
            "last_run_timestamp": None,
            "success": False,
            "error": None,
            "sources_fetched": 0,
            "currencies_updated": 0,
            "pricing_categories": 0,
        }
        
        if job_status:
            job_info.update({
                "status": job_status.get("status", "unknown"),
                "last_run": job_status.get("last_run"),
                "last_run_timestamp": job_status.get("last_run_timestamp"),
                "success": job_status.get("status") == "success",
                "error": job_status.get("error"),
                "sources_fetched": job_status.get("sources_fetched", 0),
                "currencies_updated": job_status.get("currencies_updated", 0),
                "pricing_categories": job_status.get("pricing_categories", 0),
            })
        
        dashboard_data = {
            "job_status": job_info,
            "current_pricing": {
                "last_updated": pricing_meta.get("last_updated"),
                "sources": pricing_meta.get("sources", []),
                "total_currencies_configured": len(current_pricing.get("currency_rates", {})) if current_pricing else 0,
            },
            "historical_backups": {
                "total_count": history_count,
                "max_allowed": 2,
                "backups": backup_details
            },
            "scheduling": {
                "next_scheduled_run": next_run.isoformat(),
                "time_until_next_run_seconds": int(time_until_next.total_seconds()),
                "schedule": "Daily at 00:00 UTC",
            },
            "manual_trigger_endpoint": "/admin/refresh-prices",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Cache admin dashboard for 1 minute (short TTL for freshness)
        from fastapi.responses import JSONResponse
        response = JSONResponse(content=dashboard_data)
        response.headers["Cache-Control"] = "private, max-age=60, must-revalidate"
        response.headers["Vary"] = "Accept-Encoding"
        return response
    except Exception as e:
        logger.error(f"Error fetching admin dashboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/messages")
@limiter.limit(RATE_LIMITS["admin"])
async def get_admin_messages(request: Request, admin: dict = Depends(verify_admin_token)):
    """Fetch contact messages for admin dashboard"""
    try:
        db = Database.get_db()
        if db is None:
            raise HTTPException(status_code=503, detail="Database not connected")
        
        # Get latest 50 messages
        cursor = db.contact_messages.find().sort("created_at", -1).limit(50)
        messages = await cursor.to_list(length=50)
        
        # Convert ObjectId to string
        for msg in messages:
            msg["_id"] = str(msg["_id"])
            
        return {"messages": messages}
    except Exception as e:
        logger.error(f"Error fetching messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/refresh-prices")
@limiter.limit(RATE_LIMITS["admin"])
async def refresh_prices(request: Request, admin: dict = Depends(verify_admin_token)):
    """Manually trigger price fetch - protected endpoint"""
    try:
        logger.info(f"Manual price refresh triggered by admin: {admin.get('sub')}")
        success = await PricingFetcher.fetch_latest_prices()
        if success:
            # Reload the new data into memory
            await PricingService.load_dynamic_prices()
            return {
                "status": "success",
                "message": "Pricing data refreshed successfully",
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to refresh pricing data")
    except Exception as e:
        logger.error(f"Error refreshing prices: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, credentials: dict = Body(...)):
    """Admin login endpoint - returns JWT token"""
    username = credentials.get('username')
    password = credentials.get('password')
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    token = authenticate_admin(username, password)
    if token:
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 3600
        }
    raise HTTPException(
        status_code=401,
        detail="Invalid credentials"
    )

@app.get("/pricing/status")
@limiter.limit(RATE_LIMITS["pricing_status"])
async def get_pricing_status(request: Request):
    """Get current pricing configuration status"""
    try:
        db = Database.get_db()
        if db is not None:
            pricing_doc = await db.pricing.find_one({"_id": "latest_pricing"})
            if pricing_doc:
                meta = pricing_doc.get("meta", {})
                return {
                    "using_database": True,
                    "last_updated": meta.get("last_updated"),
                    "sources": meta.get("sources", []),
                    "cloud_multipliers": pricing_doc.get("multi_cloud", PricingService.CLOUD_MULTIPLIERS),
                    "currencies_available": len(pricing_doc.get("currency_rates", {}))
                }
        
        return {
            "using_database": False,
            "last_updated": None,
            "sources": ["Hardcoded defaults"],
            "cloud_multipliers": PricingService.CLOUD_MULTIPLIERS,
            "currencies_available": len(PricingService.CURRENCY_RATES)
        }
    except Exception as e:
        logger.error(f"Error getting pricing status: {e}")
        return {
            "using_database": False,
            "error": str(e),
            "cloud_multipliers": PricingService.CLOUD_MULTIPLIERS,
            "currencies_available": len(PricingService.CURRENCY_RATES)
        }

@app.get("/providers")
@limiter.limit(RATE_LIMITS["providers"])
async def get_cloud_providers(request: Request):
    """Get list of all supported cloud providers with their multipliers and categories"""
    def categorize(provider: str) -> str:
        major = ["AWS", "Azure", "GCP", "Oracle Cloud", "IBM Cloud"]
        dev = ["DigitalOcean", "Linode", "Vultr", "Hetzner"]
        indian = ["Tata IZO", "CtrlS", "Netmagic", "Yotta"]
        if provider in major:
            return "Major Global"
        elif provider in dev:
            return "Developer-Focused"
        elif provider in indian:
            return "Indian Providers"
        return "Regional/Specialized"
    
    return {
        "providers": [
            {
                "name": provider,
                "multiplier": multiplier,
                "category": categorize(provider)
            }
            for provider, multiplier in PricingService.CLOUD_MULTIPLIERS.items()
        ]
    }
