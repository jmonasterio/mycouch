# Security Checklist for Public Repository

This document ensures the CouchDB JWT Proxy project is safe for public release on GitHub.

## Secrets Management

### Files to Never Commit

- ✅ `.env` - Contains real secrets (in `.gitignore`)
- ✅ `.env.production` - Production environment file (in `.gitignore`)
- ✅ Any `config/*.local.json` files (in `.gitignore`)

### Required Environment Variables

For local development, create `.env` with these values: TBD

## Code Review Checklist

- [x] No hardcoded API keys in source code
- [x] No hardcoded database credentials in source code
- [x] No hardcoded secrets in `main.py`
- [x] CLERK_ISSUER_URL must be configured via environment variable
- [x] All sensitive config must come from `.env`

## Configuration Files

### `.env.example`
Template for developers with clear documentation:
- Explains each configuration option
- Includes examples and default values
- No real secrets, all values are placeholders or examples
- Instructions for generating secure random secrets

### `.env` (Local Development)
- Contains REAL secrets for development
- MUST be in `.gitignore`
- MUST NOT be committed

## GitHub Actions Secrets

When deploying with GitHub Actions, set these as repository secrets:

```
DEPLOY_SSH_PRIVATE_KEY      # SSH key for server deployment
DEPLOY_USER                 # Linux username
DEPLOY_HOST                 # Server IP or domain
DEPLOY_PORT                 # SSH port (default 22)
```

Production environment variables (set on server):

```
CLERK_ISSUER_URL           # Your Clerk instance
COUCHDB_INTERNAL_URL       # Internal CouchDB URL
COUCHDB_USER               # CouchDB username
COUCHDB_PASSWORD           # CouchDB password
PROXY_HOST                 # Listen IP
PROXY_PORT                 # Listen port
```

## Validation

The application validates configuration on startup:

```
# If using Clerk JWT (ENABLE_CLERK_JWT=true):
CLERK_ISSUER_URL must be set
```

If either validation fails, the application will refuse to start with a clear error message.

## Before Making Public

### Pre-Commit Checks

Run before committing:

```bash
# Check for accidental secrets
grep -r "admin:" . --include="*.py" --include="*.md"
grep -r "password" . --include="*.py" --include="*.env" 2>/dev/null | grep -v "\.example\|#"

# Verify .gitignore is correct
cat .gitignore | grep ".env"

# Verify no .env files are committed
git status | grep "\.env$"
```

### Final Review

Before pushing to public repository:

1. **Run security checks:**
   ```bash
   grep -r "password" main.py               # Should NOT find hardcoded value
   git ls-files | grep ".env$"              # Should be empty
   ```

2. **Verify templates exist:**
   ```bash
   ls -la .env.example                      # Must exist
   ```

3. **Verify documentation:**
   - README.md explains how to set up `.env`
   - GITHUB_ACTIONS_DEPLOY.md explains GitHub Secrets
   - LINUX_DEPLOYMENT_PROXY.md explains production configuration

## Deployment Configuration

### Local Development

1. Copy template: `cp .env.example .env`
2. Edit `.env` with local values
3. Ensure `.env` is in `.gitignore`

### Production Deployment

1. **GitHub Actions:**
   - Add secrets to GitHub repository (Settings → Secrets)
   - Workflow uses secrets via `${{ secrets.SECRET_NAME }}`

2. **Linux Server:**
   - Create `.env` file on server with production values
   - Do NOT deploy `.env` from repository (contains dev values)
   - Never store `.env` in git with production values

3. **Environment Setup:**
   ```bash
   # On Linux server
   cd /opt/couchdb-jwt-proxy

   # Copy and edit configuration
   cp .env.example .env
   nano .env

   # Verify required values are set
   grep "^COUCHDB_PASSWORD=" .env  # Must not be empty
   ```

## Secrets Rotation

When you need to rotate secrets:

1. **GitHub Actions SSH Key:**
   - Generate new key: `ssh-keygen -t ed25519 -f ~/.ssh/github_deploy_new -N ""`
   - Update GitHub Secrets with new private key
   - Update server's `~/.ssh/authorized_keys` with new public key

3. **CouchDB Credentials:**
   - Change password in CouchDB
   - Update `COUCHDB_PASSWORD` in production `.env`
   - Restart proxy: `sudo systemctl restart couchdb-proxy`

## Monitoring for Leaks

After making public, monitor for accidental commits:

```bash
# Check git history for secrets (if accidentally committed)
git log -p | grep -i "password\|secret\|api_key" | head -10

```
## Compliance

- ✅ No hardcoded secrets in code
- ✅ No real credentials in `.env.example`
- ✅ `.gitignore` properly configured
- ✅ Configuration validation on startup
- ✅ Clear documentation for setup
- ✅ Deployment guide included

## Additional Resources

- See `README.md` for setup instructions
- See `GITHUB_ACTIONS_DEPLOY.md` for CI/CD deployment
- See `LINUX_DEPLOYMENT_PROXY.md` for server deployment
- See `.env.example` for all configuration options

---

**Status:** ✅ Ready for public repository
