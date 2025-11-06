# Pre-Public Release Checklist

Before pushing mycouch to a public GitHub repository, use this checklist to verify everything is secure.

## Quick Start

```bash
# 1. Run security verification
./verify_security.sh

# 2. Review the output
# 3. Fix any errors
# 4. Run again to confirm
./verify_security.sh

# 5. If all green, you're ready to go!
```

---

## Manual Verification Steps

### Step 1: Verify No Secrets in Code

```bash
# Check main.py for hardcoded passwords/keys
grep -n "password" main.py | grep -v "os.getenv" | grep -v "#"
grep -n "secret" main.py | grep -v "os.getenv" | grep -v "#"
grep -n "api_key" main.py | grep -v "os.getenv" | grep -v "#"

# Should return: nothing or only comments
```

### Step 2: Verify .env Files Are Protected

```bash
# Check if .env is in git (should NOT be)
git ls-files | grep "\.env$"
git ls-files | grep "api_keys.json$"

# Output should be empty. If not, remove them:
git rm --cached .env config/api_keys.json
git commit -m "Remove secrets from git tracking"
```

### Step 3: Check .gitignore

```bash
# Verify .gitignore has required entries
grep "\.env" .gitignore
grep "api_keys.json" .gitignore

# Both should return results
```

### Step 4: Verify Templates Exist

```bash
# Check template files exist
ls -la .env.example
ls -la config/api_keys.json.example

# Both should exist
```

### Step 5: Review Documentation

```bash
# Verify security documentation exists
ls -la SECURITY_CHECKLIST.md
ls -la SECURITY_AUDIT_SUMMARY.md
ls -la README.md

# All should exist
```

---

## Security Audit Summary

### ✅ Fixes Applied

| Issue | Status | Details |
|-------|--------|---------|
| Hardcoded JWT_SECRET | ✅ Fixed | Removed default fallback value from main.py |
| API keys in repo | ✅ Fixed | Moved config/api_keys.json to .gitignore |
| Real secrets in .env | ✅ Fixed | Cleared and replaced with placeholders |
| Missing validation | ✅ Fixed | Added startup config validation |
| Placeholder author | ✅ Fixed | Updated pyproject.toml author |
| Poor documentation | ✅ Fixed | Created comprehensive .env.example |
| No security guide | ✅ Fixed | Created SECURITY_CHECKLIST.md |

---

## Files Modified/Created

### Modified
- ✅ `main.py` - Removed default JWT_SECRET, added validation
- ✅ `pyproject.toml` - Updated author name
- ✅ `.env` - Cleared real secrets
- ✅ `.env.example` - Comprehensive template with instructions
- ✅ `.gitignore` - Added config file patterns

### Created
- ✅ `config/api_keys.json.example` - API keys template
- ✅ `SECURITY_CHECKLIST.md` - Security compliance checklist
- ✅ `SECURITY_AUDIT_SUMMARY.md` - Detailed audit report
- ✅ `PRE_PUBLIC_RELEASE_CHECKLIST.md` - This file
- ✅ `verify_security.sh` - Automated verification script

---

## Before You Commit

### Run the Security Script

```bash
./verify_security.sh
```

Expected output:
```
🔍 Security Verification for mycouch
======================================

1️⃣  Checking for hardcoded secrets in Python files...
✅ PASS: No hardcoded JWT_SECRET in main.py
✅ PASS: No hardcoded passwords in main.py
✅ PASS: No hardcoded API keys in main.py

2️⃣  Checking if secrets files are in git...
✅ PASS: .env file is NOT tracked in git
✅ PASS: config/api_keys.json is NOT tracked in git

... (more checks)

📊 Results:
Errors:   0
Warnings: 0

✅ SECURITY CHECK PASSED
   Ready to push to public repository
```

---

## Before You Push

### Create a Personal .env for Testing

```bash
# Copy template
cp .env.example .env

# Generate a secure JWT_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Edit .env and set:
# JWT_SECRET=<generated_value>
# COUCHDB_PASSWORD=<your_local_password>
```

### Test Locally

```bash
# Start Docker CouchDB
docker run -d -e COUCHDB_PASSWORD=password -p 5984:5984 couchdb:latest

# Install dependencies
uv sync

# Run tests
pytest test_main.py -v

# Start proxy
python -m uvicorn main:app --reload

# In another terminal, test health endpoint
curl http://localhost:5985/health
```

### Verify No Secrets in History

```bash
# Check git history for accidental secrets
git log -p -S "admin:" -- "*.py" | head -20
git log -p -S "password=" -- "*.env*" | head -20

# Should return nothing
```

---

## GitHub Actions Setup

After pushing to public repo:

### 1. Add GitHub Secrets

Navigate to: **Settings → Secrets and variables → Actions**

Add these secrets:
- `DEPLOY_SSH_PRIVATE_KEY` - Your SSH private key
- `DEPLOY_USER` - Linux username (e.g., `ubuntu`)
- `DEPLOY_HOST` - Server IP or domain
- `DEPLOY_PORT` - SSH port (optional, defaults to 22)

### 2. Create Personal .env on Server

SSH to your production server:

```bash
cd /opt/couchdb-jwt-proxy

# Copy template
sudo cp .env.example .env

# Edit with real values
sudo nano .env

# Set:
# JWT_SECRET=<generate new one>
# CLERK_ISSUER_URL=<your_clerk_url>
# COUCHDB_PASSWORD=<your_password>
```

### 3. Verify Deployment Works

```bash
# Push to main branch (or manually trigger)
git push origin main

# GitHub Actions workflow will:
# 1. Copy files to server
# 2. Stop proxy service
# 3. Update files
# 4. Reinstall dependencies
# 5. Start proxy service
# 6. Verify health endpoint
```

---

## Production Checklist

### Before Going Live

- [ ] Security verification script passes (`./verify_security.sh`)
- [ ] No real secrets in git history
- [ ] All environment variables documented in `.env.example`
- [ ] `.env` file is NOT in git repository
- [ ] `config/api_keys.json` is NOT in git repository
- [ ] `SECURITY_CHECKLIST.md` exists and is accurate
- [ ] GitHub Actions workflow is configured
- [ ] SSH keys are set up for deployment
- [ ] Production `.env` is created on server (with real secrets)
- [ ] Proxy service is enabled and auto-starts on reboot
- [ ] Health endpoint is accessible from internet

---

## If You Accidentally Committed Secrets

### Option 1: Fresh Start (Recommended)

```bash
# 1. Generate new secrets everywhere
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Update production server .env with new secrets
# 3. Rotate GitHub Actions SSH key
# 4. Update GitHub Secrets

# 5. Force push to remove from history (use with caution)
git reset --soft HEAD~1  # Undo last commit
git restore .env config/api_keys.json  # Remove files from staging
git commit -m "Remove secrets"
git push origin main --force-with-lease
```

### Option 2: Rewrite History

```bash
# Use git-filter-repo to remove secrets from history
# (More complex, see: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

pip install git-filter-repo
git filter-repo --invert-paths --path .env
git filter-repo --invert-paths --path config/api_keys.json
```

---

## FAQ

### Q: Is .env safe if it's in .gitignore?

**A:** Yes, it won't be committed. However:
- Never commit with real secrets, even by accident
- Use `./verify_security.sh` to double-check before pushing
- Always run the verification script as part of your workflow

### Q: Do I need to worry about old commits?

**A:** Only if secrets were in old commits. If you just generated the code:
- New `.env.example` has no secrets ✅
- Real `.env` is in .gitignore ✅
- No old commits with secrets exist ✅

### Q: What if I see "401 /wsman" in logs?

**A:** That's a security probe (not your code). The proxy is working correctly by rejecting it. See `SECURITY_AUDIT_SUMMARY.md` for details.

### Q: How do I rotate secrets in production?

**A:** See `SECURITY_CHECKLIST.md` → "Secrets Rotation" section.

---

## Quick Reference

### Before Public Release
```bash
./verify_security.sh                    # ✅ Run this first
git diff --staged                       # Check what's being committed
git log --oneline -n 10                 # Verify clean history
```

### After Public Release
```bash
curl https://your-domain.com/health     # Verify proxy is running
sudo systemctl status couchdb-proxy     # Check service status
```

---

## Getting Help

If something fails:

1. **Run verification script again:**
   ```bash
   ./verify_security.sh -v
   ```

2. **Check documentation:**
   - `SECURITY_CHECKLIST.md` - General security info
   - `SECURITY_AUDIT_SUMMARY.md` - Detailed audit report
   - `README.md` - How to use the proxy
   - `LINUX_DEPLOYMENT_PROXY.md` - Deployment guide

3. **Common issues:**
   - See `TROUBLESHOOTING.md` (if it exists)
   - Check GitHub Actions logs for deployment issues
   - Review systemd logs: `sudo journalctl -u couchdb-proxy -n 50`

---

## Summary

### What Was Done
- ✅ Removed all hardcoded secrets from code
- ✅ Protected real secrets in `.gitignore`
- ✅ Created comprehensive templates
- ✅ Added startup validation
- ✅ Created security documentation
- ✅ Created automated verification script

### What You Need to Do
1. Run `./verify_security.sh` to verify all is secure
2. Generate new JWT_SECRET for production
3. Create `.env` file on production server with real values
4. Set up GitHub Actions secrets
5. Deploy and verify health endpoint

### Status
🚀 **READY FOR PUBLIC RELEASE**

All critical security issues fixed. Ready to push to GitHub! 🎉
