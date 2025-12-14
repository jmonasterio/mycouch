# Deploying MyCouch to argw.com

MyCouch is the CouchDB JWT authentication proxy that runs at `https://argw.com/mycouch`. It handles JWT validation and multi-tenant isolation before proxying requests to CouchDB.

---

## Prerequisites

- A GitHub account with repo access
- Git installed on your computer
- The MyCouch code in a local folder
- SSH access to argw.com (as jm user)

---

## Deploying to argw.com via GitHub Actions

### Step 1: SSH Configuration

If not already done, add this to `~/.ssh/config`:

```
Host argw.com
    User jm
    IdentityFile ~/.ssh/argw_deploy
    StrictHostKeyChecking accept-new
```

### Step 2: Configure GitHub Secrets

In your GitHub repo → Settings → Secrets and variables → Actions → New repository secret:

1. **`DEPLOY_KEY`**
   - Contents of `~/.ssh/argw_deploy` (private key file, entire contents)
   - Same key as used for roady deployment

2. **`DEPLOY_USER`**
   - Value: `jm`

3. **`KNOWN_HOSTS`**
   - Run locally: `ssh-keyscan argw.com`
   - Paste the entire output
   - Same as used for roady deployment

### Step 3: Automatic Deployment

The GitHub Actions workflow in `.github/workflows/deploy.yml` will:

- Run tests first (must pass to deploy)
- Deploy on every push to `main` branch
- Use rsync to sync files to `/var/www/argw.com/mycouch/`
- Exclude Python cache, venv, and .env files
- Attempt to restart the service on the server

You can also trigger manual deployments from Actions tab.

---

## Manual Deployment

To deploy manually from your local machine:

```bash
# Test that you can connect
ssh jm@argw.com "ls -la /var/www/argw.com/mycouch/"

# Deploy the code
rsync -avz \
  --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.venv' \
  --exclude='.uv' \
  --exclude='.env' \
  ./ \
  jm@argw.com:/var/www/argw.com/mycouch/

# Log in and restart (if using systemd)
ssh jm@argw.com "cd /var/www/argw.com/mycouch && sudo systemctl restart mycouch"
```

---

## Server Architecture

```
argw.com/
├── /var/www/argw.com/
│   ├── roady/          (PWA frontend → https://argw.com/roady)
│   └── mycouch/        (FastAPI proxy → https://argw.com/mycouch)
├── /opt/couchdb/       (CouchDB backend - main application database)
│   ├── bin/couchdb
│   ├── etc/couchdb.ini (config)
│   └── data/           (databases: couch-sitter, roady)
└── /var/log/couchdb/   (logs)
```

---

## Running MyCouch Locally

For development or testing:

```bash
# Install dependencies
make dev

# Run with auto-reload
make dev-run
```

The proxy will start on `http://localhost:5985` and forward requests to CouchDB at `http://localhost:5984`.

---

## Environment Variables

MyCouch uses a `.env` file for configuration. See `.env.example` for required variables:

```bash
make env-setup
```

**Important:** The `.env` file is excluded from deployment (contains secrets like CLERK_SECRET_KEY). You must configure it manually on the server.

---

## Testing

Before deploying, ensure tests pass:

```bash
make test
```

For coverage report:

```bash
make test-cov
```

Tests must pass in CI before deployment proceeds.

---

## Troubleshooting

### Service Won't Start

Check logs on the server:

```bash
ssh jm@argw.com "sudo journalctl -u mycouch -n 50 --no-pager"
```

### Permission Denied on rsync

Ensure jm user has write access to `/var/www/argw.com/mycouch/`:

```bash
ssh jm@argw.com "ls -la /var/www/argw.com/"
```

If permissions are wrong:

```bash
ssh jm@argw.com "sudo chown -R jm:jm /var/www/argw.com/mycouch"
```

### Test Failures in CI

View the Actions log in GitHub to see which tests failed. Common issues:

- CouchDB not running locally (tests need it for integration tests)
- Missing environment variables
- Clerk API issues

Run tests locally first:

```bash
make test
```

---

## Production Notes

- The `.env` file must be manually created/updated on the server with production secrets
- CouchDB must be running on the server and accessible to MyCouch
- MyCouch uses port 5985 by default (should be proxied through nginx/apache to https://argw.com/mycouch)
- Service must be configured to auto-start on reboot (systemd unit file)
