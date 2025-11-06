# GitHub Actions Deployment Setup

This guide explains how to set up GitHub Actions to automatically deploy the CouchDB JWT Proxy to your Linux server via SCP.

## Prerequisites

- GitHub repository for the mycouch project
- Linux server with sudo access
- SSH access to your server configured with key-based authentication

## Step 1: Generate SSH Key Pair for Deployment

**On your local machine:**

```bash
# Generate a new SSH key specifically for deployment
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "github-actions-deploy"

# Get the public key
cat ~/.ssh/github_deploy.pub
```

## Step 2: Add Public Key to Linux Server

**On your Linux server:**

```bash
# Create .ssh directory if it doesn't exist
mkdir -p ~/.ssh

# Add the public key to authorized_keys
# (Replace with the public key from step 1)
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI..." >> ~/.ssh/authorized_keys

# Secure permissions
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Alternatively, if you already have SSH key access, copy the public key:

```bash
# On your local machine
ssh-copy-id -i ~/.ssh/github_deploy your-user@your-server.com
```

## Step 3: Get SSH Private Key Content

**On your local machine:**

```bash
# Display the private key (you'll copy this into GitHub Secrets)
cat ~/.ssh/github_deploy
```

The output should look like:
```
-----BEGIN OPENSSH PRIVATE KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC...
...
-----END OPENSSH PRIVATE KEY-----
```

## Step 4: Add GitHub Secrets

1. Go to your GitHub repository
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add these secrets:

| Secret Name | Value | Description |
|---|---|---|
| `DEPLOY_SSH_PRIVATE_KEY` | Your SSH private key from Step 3 | Multi-line private key |
| `DEPLOY_USER` | Your Linux username | e.g., `ubuntu`, `root`, `ec2-user` |
| `DEPLOY_HOST` | Your server's IP or domain | e.g., `your-domain.com` or `192.168.1.100` |
| `DEPLOY_PORT` | SSH port (optional) | Default: `22` |

**Example:**

- `DEPLOY_SSH_PRIVATE_KEY`: (paste entire private key, including BEGIN/END lines)
- `DEPLOY_USER`: `ubuntu`
- `DEPLOY_HOST`: `your-domain.com`
- `DEPLOY_PORT`: `22` (optional)

## Step 5: Verify Workflow File

The workflow file should be at: `.github/workflows/deploy-proxy.yml`

It will automatically:
1. Trigger on push to `main` branch
2. Copy proxy files via SCP to `/tmp/couchdb-proxy-update/`
3. SSH into your server and:
   - Stop the proxy service
   - Copy updated files to `/opt/couchdb-jwt-proxy/`
   - Reinstall dependencies with `uv sync`
   - Start the proxy service
   - Verify the service is running
   - Check the health endpoint

## Step 6: Manual Trigger (Optional)

You can manually trigger the deployment without pushing code:

1. Go to your GitHub repository
2. Click **Actions**
3. Select **Deploy CouchDB JWT Proxy** workflow
4. Click **Run workflow** → **Run workflow**

## Step 7: Monitor Deployment

1. Go to **Actions** tab in your repository
2. Click on the workflow run to see real-time logs
3. Each step will show success/failure status

## Troubleshooting

### "SSH key rejected"

- Verify the private key was copied correctly (check for extra spaces/newlines)
- Confirm the public key is in `~/.ssh/authorized_keys` on the server
- Check server logs: `sudo journalctl -u sshd -n 50`

### "Permission denied (publickey)"

```bash
# On your local machine, test SSH connection
ssh -p 22 -i ~/.ssh/github_deploy your-user@your-server.com "echo 'Connection successful'"
```

### "Service failed to start"

Check the deployment logs in GitHub Actions, then SSH to server and review:

```bash
sudo journalctl -u couchdb-proxy -n 50
```

### "SCP: command not found"

Ensure `openssh-client` is available. GitHub's `ubuntu-latest` runner includes it by default.

### "sudo: no password prompt" hangs

The workflow uses `ssh` with a here-document (`<< 'EOF'`). The `sudo` commands should work without a password prompt if your user has `NOPASSWD` configured in sudoers (recommended for deployment).

**Configure sudoers on server:**

```bash
sudo visudo

# Add this line at the bottom:
your-user ALL=(ALL) NOPASSWD: /bin/systemctl, /bin/cp, /bin/chown, /bin/chmod, /usr/bin/journalctl
```

## Security Best Practices

1. **Use a dedicated deployment user** - Create a restricted account for deployments
2. **Limit SSH key permissions** - Only allow this key to execute necessary commands
3. **Use NOPASSWD sudoers** - Prevents password prompts in automated deployments
4. **Rotate SSH keys periodically** - Replace old keys with new ones
5. **Monitor deployments** - Review GitHub Actions logs after each deployment
6. **Keep secrets secure** - Never commit `.env` files or private keys to git

## Optional: Restrict Deployment Key with sudoers

For maximum security, restrict what the deployment key can run:

```bash
sudo visudo

# Add specific commands allowed without password
your-user ALL=(ALL) NOPASSWD: /bin/systemctl stop couchdb-proxy, \
                              /bin/systemctl start couchdb-proxy, \
                              /bin/systemctl status couchdb-proxy, \
                              /bin/cp -r /tmp/couchdb-proxy-update/* /opt/couchdb-jwt-proxy/, \
                              /bin/chown -R nobody:nogroup /opt/couchdb-jwt-proxy, \
                              /bin/chmod -R 755 /opt/couchdb-jwt-proxy, \
                              /usr/bin/journalctl -u couchdb-proxy
```

## Automatic Deployments

The workflow triggers automatically on:

1. **Push to main branch** - Deployments happen immediately after merge
2. **Manual trigger** - Via GitHub Actions UI

### Disabling Auto-Deploy

If you want to require manual approval, modify `.github/workflows/deploy-proxy.yml`:

```yaml
on:
  # Remove or comment out the push trigger
  # push:
  #   branches:
  #     - main
  workflow_dispatch:
```

Then deployments only happen via manual trigger in GitHub Actions.

## Rollback Procedure

If deployment causes issues:

```bash
# On your Linux server, manually rollback
sudo systemctl stop couchdb-proxy
cd /opt/couchdb-jwt-proxy
git checkout main  # If you're using git
# OR manually restore from backup:
# sudo cp -r /backup/couchdb-proxy-YYYYMMDD/* /opt/couchdb-jwt-proxy/
sudo systemctl start couchdb-proxy
```

## Environment Variables

The workflow uses these GitHub Secrets:

- `DEPLOY_SSH_PRIVATE_KEY` - Private SSH key for authentication
- `DEPLOY_USER` - Username for SSH connection
- `DEPLOY_HOST` - Server IP or domain
- `DEPLOY_PORT` - SSH port (defaults to 22 if not set)

## Files Deployed

The workflow copies these files from your repository:

- `main.py` - Proxy application
- `pyproject.toml` - Python dependencies
- `.env.example` - Example configuration

**Note:** The `.env` file is NOT deployed automatically (contains secrets). You must configure it manually on the server.

## Next Steps

1. Generate SSH key pair (Step 1)
2. Add public key to server (Step 2)
3. Add GitHub Secrets (Step 4)
4. Push to main branch to test deployment
5. Monitor the GitHub Actions workflow for success
6. Verify proxy is running: `curl https://your-domain.com/health`
