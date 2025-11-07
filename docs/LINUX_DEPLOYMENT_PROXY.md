# Deploying CouchDB JWT Proxy to Linux

This guide explains how to deploy the CouchDB JWT Proxy Python application on a Linux server.

## Prerequisites

- Linux server (Ubuntu 20.04+ or similar)
- Python 3.9+
- `pip` or `apt` package manager
- Root or sudo access
- Domain name (for HTTPS in production)
- Git (for cloning the repository)

## Step 1: Install Python and Dependencies

```bash
# Update system packages
sudo apt update
sudo apt upgrade -y

# Install Python and pip
sudo apt install -y python3 python3-pip python3-venv git curl

# Verify installation
python3 --version
pip3 --version
```

## Step 2: Download the Proxy

**⚠️ SECURITY NOTE:** Do NOT use git credentials on production servers. Instead, copy files from your development machine.

### Option A: Copy Files from Development Machine (Recommended)

```bash
# On your development machine
# Copy all proxy files to the server via SCP/SFTP
scp -r /path/to/mycouch/* your-user@your-server.com:/tmp/couchdb-proxy/

# On the Linux server
sudo mkdir -p /opt/couchdb-jwt-proxy
sudo cp -r /tmp/couchdb-proxy/* /opt/couchdb-jwt-proxy/
sudo chown -R nobody:nogroup /opt/couchdb-jwt-proxy
sudo chmod -R 755 /opt/couchdb-jwt-proxy
```

### Option B: Manual File Transfer via SFTP

```bash
# Use SFTP client (FileZilla, WinSCP, etc.) to upload:
# - main.py
# - pyproject.toml
# - .env (after configuring with production values)
# - Any other necessary files

# Then set permissions on the server:
sudo chown -R nobody:nogroup /opt/couchdb-jwt-proxy
sudo chmod -R 755 /opt/couchdb-jwt-proxy
```

### Option C: Using SSH Keys with Git (If You Must Use Git)

If you prefer git, set up SSH keys instead of storing credentials:

```bash
# On the server, generate SSH key
ssh-keygen -t ed25519 -f ~/.ssh/id_github -N ""

# Add the public key to GitHub:
cat ~/.ssh/id_github.pub

# Then clone using SSH (not HTTPS)
git clone git@github.com:your-username/mycouch.git /opt/couchdb-jwt-proxy
```

**⚠️ WARNING:** Only use Option C if the repository is private and you're comfortable managing SSH keys on the server. Option A is recommended.

## Step 3: Install Python Dependencies

```bash
cd /opt/couchdb-jwt-proxy

# Install uv package manager (recommended)
pip3 install uv

# Install dependencies
uv sync

# If uv fails, use pip directly:
pip3 install -r requirements.txt

# Or install manually:
pip3 install fastapi uvicorn pyjwt cryptography httpx python-dotenv pydantic
```

## Step 4: Configure Environment

```bash
# Copy the example .env file
cp .env.example .env

# Edit the configuration
nano .env
```

**Edit these values for production:**

```bash
# Enable Clerk JWT validation (set to true if using Clerk)
CLERK_ISSUER_URL=https://your-clerk-instance.clerk.accounts.dev

# Generate a random JWT secret:
# python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# CouchDB internal connection
COUCHDB_INTERNAL_URL=http://localhost:5984

# CouchDB credentials (for proxy to authenticate to CouchDB)
COUCHDB_USER=admin
COUCHDB_PASSWORD=<your-couchdb-password>

# Proxy configuration
# Listen IP (0.0.0.0 = all interfaces, 127.0.0.1 = localhost only)
PROXY_HOST=0.0.0.0

# Listen port (can be 5985 or any high port)
PROXY_PORT=5985

# Logging level
LOG_LEVEL=INFO

# Tenant mode (optional)
ENABLE_TENANT_MODE=false
TENANT_CLAIM=tenant_id
TENANT_FIELD=tenant_id
```

Save and exit: `Ctrl+X`, then `Y`, then `Enter`

## Step 5: Configure Listen Address (Optional)

The proxy can listen on different IP addresses:

```bash
# In .env file

# Listen on all interfaces (default) - accessible from anywhere
PROXY_HOST=0.0.0.0
PROXY_PORT=5985

# OR listen on localhost only - not accessible from other machines
PROXY_HOST=127.0.0.1
PROXY_PORT=5985

# OR listen on specific network interface
PROXY_HOST=192.168.1.100
PROXY_PORT=5985
```

**Common configurations:**

- **Development (localhost only):** `PROXY_HOST=127.0.0.1`
- **Production (all interfaces):** `PROXY_HOST=0.0.0.0`
- **Specific interface:** `PROXY_HOST=<your-server-ip>`

## Step 6: Test Manually

```bash
# Start the proxy in foreground (for testing)
# It will use PROXY_HOST and PROXY_PORT from .env
cd /opt/couchdb-jwt-proxy
uv run uvicorn main:app

# In another terminal, test the health endpoint:
curl http://localhost:5985/health

# You should see:
# {"status":"ok","service":"couchdb-jwt-proxy","couchdb":"connected"}

# Or if PROXY_HOST is not localhost:
# curl http://<PROXY_HOST>:5985/health
```

If it works, stop the proxy: `Ctrl+C`

## Step 7: Set Up Firewall

**Allow port 5985 through the firewall:**

### Using UFW (Ubuntu)
```bash
# Enable firewall if not already
sudo ufw enable

# Allow SSH (IMPORTANT - don't lock yourself out!)
sudo ufw allow 22/tcp

# Allow proxy port
sudo ufw allow 5985/tcp

# Check rules
sudo ufw status
```

### Using firewalld (CentOS/RHEL)
```bash
# Enable firewalld
sudo systemctl enable firewalld
sudo systemctl start firewalld

# Allow proxy port
sudo firewall-cmd --permanent --add-port=5985/tcp
sudo firewall-cmd --reload

# Check rules
sudo firewall-cmd --list-all
```

## Step 8: Create Systemd Service

```bash
# Create service file
sudo nano /etc/systemd/system/couchdb-proxy.service
```

**Paste this content:**

```ini
[Unit]
Description=CouchDB JWT Proxy
After=network.target couchdb.service
Wants=network-online.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/opt/couchdb-jwt-proxy
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/couchdb-jwt-proxy/.env

# Using uv (if installed) - reads PROXY_HOST and PROXY_PORT from .env
ExecStart=/home/YOUR_USERNAME/.local/bin/uv run uvicorn main:app

# OR using python directly
# ExecStart=/usr/bin/python3 -m uvicorn main:app

Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=couchdb-proxy

# Security settings
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

**Replace:**
- `YOUR_USERNAME` with your actual Linux username
- If using python directly, uncomment the second ExecStart line
- Find uv path: `which uv` (usually `/home/username/.local/bin/uv`)
- The `EnvironmentFile` line loads all settings from .env automatically

**Enable and start the service:**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (auto-start on boot)
sudo systemctl enable couchdb-proxy

# Start the service
sudo systemctl start couchdb-proxy

# Check status
sudo systemctl status couchdb-proxy

# View logs
sudo journalctl -u couchdb-proxy -f
```

## Step 9: SSL/HTTPS Setup (Production)

Using Let's Encrypt with Certbot:

```bash
# Install certbot
sudo apt install -y certbot python3-certbot-nginx

# Get certificate (requires domain name and port 80 access)
sudo certbot certonly --standalone -d your-domain.com

# Certificates saved to:
# /etc/letsencrypt/live/your-domain.com/fullchain.pem
# /etc/letsencrypt/live/your-domain.com/privkey.pem
```

## Step 10: Set Up Nginx Reverse Proxy (Recommended)

**Install Nginx:**

```bash
sudo apt install -y nginx
```

**Create Nginx config:**

```bash
sudo nano /etc/nginx/sites-available/couchdb-proxy
```

**Paste this configuration:**

```nginx
upstream couchdb_proxy {
    server 127.0.0.1:5985;
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://couchdb_proxy;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Important: Allow long-polling connections for _changes
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

**Enable configuration:**

```bash
sudo ln -s /etc/nginx/sites-available/couchdb-proxy /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
```

## Step 11: Verify Everything Works

```bash
# Test proxy locally
curl http://localhost:5985/health

# Test from remote (replace with your IP/domain)
curl https://your-domain.com/health

# Check service status
sudo systemctl status couchdb-proxy

# View recent logs
sudo journalctl -u couchdb-proxy -n 50
```

## Step 12: Configure Roady PWA

In your Roady PWA Settings:

```
Remote DB URL: https://your-domain.com
```

(No port number needed - Nginx handles it)

## Monitoring and Logs

```bash
# Real-time logs
sudo journalctl -u couchdb-proxy -f

# Last 50 lines
sudo journalctl -u couchdb-proxy -n 50

# Today's logs
sudo journalctl -u couchdb-proxy --since today

# Search for errors
sudo journalctl -u couchdb-proxy | grep "ERROR\|401"

# Check service status
sudo systemctl status couchdb-proxy
```

## Troubleshooting

### Port 5985 not accessible

```bash
# Check if service is listening
sudo netstat -tlnp | grep 5985
# or
sudo ss -tlnp | grep 5985

# If showing 127.0.0.1 instead of 0.0.0.0:
# - Check systemd service ExecStart line

# Check firewall
sudo ufw status
sudo firewall-cmd --list-all
```

### Service won't start

```bash
# Check logs for error details
sudo journalctl -u couchdb-proxy -n 100

# Test manually
cd /opt/couchdb-jwt-proxy
python3 -m uvicorn main:app --host 0.0.0.0 --port 5985

# Check Python/dependency errors
python3 -c "import fastapi; print('OK')"
```

### Connection refused to CouchDB

```bash
# Verify CouchDB is running
curl http://localhost:5984/

# Check COUCHDB_INTERNAL_URL in .env
cat /opt/couchdb-jwt-proxy/.env | grep COUCHDB_INTERNAL_URL

# Check CouchDB credentials
cat /opt/couchdb-jwt-proxy/.env | grep COUCHDB_USER
```

### 502 Bad Gateway (Nginx)

```bash
# Check Nginx logs
sudo tail -f /var/log/nginx/error.log

# Check if upstream is working
curl http://127.0.0.1:5985/health

# Test Nginx config
sudo nginx -t
```

### 401 Unauthorized Errors

```bash
# Check Clerk JWT configuration
cat /opt/couchdb-jwt-proxy/.env | grep CLERK

# View authentication logs
sudo journalctl -u couchdb-proxy | grep "401"

# Verify Clerk JWKS endpoint is accessible
curl https://your-clerk-issuer/.well-known/jwks.json
```

## Backup Configuration

```bash
# Backup proxy files and .env
sudo cp -r /opt/couchdb-jwt-proxy /backup/couchdb-proxy-$(date +%Y%m%d)

# Or create a tarball
sudo tar czf /backup/couchdb-proxy-$(date +%Y%m%d).tar.gz /opt/couchdb-jwt-proxy
```

## Updating the Proxy

**⚠️ SECURITY NOTE:** Do NOT use git pull on production. Copy updated files from your development machine instead.

```bash
# Stop service
sudo systemctl stop couchdb-proxy

# On your development machine, copy updated files
scp -r /path/to/mycouch/* your-user@your-server.com:/tmp/couchdb-proxy-update/

# On the Linux server, copy updated files
sudo cp -r /tmp/couchdb-proxy-update/* /opt/couchdb-jwt-proxy/
sudo chown -R nobody:nogroup /opt/couchdb-jwt-proxy

# Reinstall dependencies if needed
cd /opt/couchdb-jwt-proxy
uv sync

# Start service
sudo systemctl start couchdb-proxy

# Verify
sudo systemctl status couchdb-proxy

# Check logs
sudo journalctl -u couchdb-proxy -n 50
```

**Alternative: Using git with SSH keys** (if you set that up earlier):

```bash
sudo systemctl stop couchdb-proxy

cd /opt/couchdb-jwt-proxy
sudo git pull origin main

uv sync

sudo systemctl start couchdb-proxy
```

## Production Checklist

- [ ] Python 3.9+ installed
- [ ] Dependencies installed (`uv sync` or `pip install`)
- [ ] `.env` configured with production values
- [ ] `COUCHDB_INTERNAL_URL` points to internal CouchDB
- [ ] `COUCHDB_USER` and `COUCHDB_PASSWORD` set correctly
- [ ] Firewall allows port 5985 (or 443 if using Nginx)
- [ ] Systemd service created and enabled
- [ ] SSL certificate configured (Let's Encrypt)
- [ ] Nginx reverse proxy configured
- [ ] Logs monitored and rotating
- [ ] Backup strategy in place
- [ ] Health check endpoint accessible from remote
- [ ] Roady PWA configured with correct URL
- [ ] Service auto-restarts on failure
- [ ] Service auto-starts on system reboot

## Performance Tuning

```bash
# Monitor service resource usage
sudo systemctl status couchdb-proxy
top -p $(pgrep -f "uvicorn main:app")

# Increase file limits if needed
sudo nano /etc/security/limits.conf
# Add: * soft nofile 65536
# Add: * hard nofile 65536

# Check current limits
ulimit -n
```

## Support and Debugging

For detailed debugging:

1. Enable DEBUG logging temporarily:
   ```bash
   # In .env: LOG_LEVEL=DEBUG
   sudo systemctl restart couchdb-proxy
   ```

2. Check proxy logs: `sudo journalctl -u couchdb-proxy -f`
3. Check Nginx logs: `sudo tail -f /var/log/nginx/error.log`
4. Verify connectivity: `curl http://localhost:5985/health`
5. See `CLERK_SETUP.md` for authentication issues
6. See `README.md` for API reference
