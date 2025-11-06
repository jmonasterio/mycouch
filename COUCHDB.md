CouchDB Setup Notes – /opt/couchdb (localhost-only)
1️⃣ Installation

CouchDB installed manually in /opt/couchdb

Do not rely on apt version if you want custom path

Erlang/BEAM included in /opt/couchdb/bin/../erts-*

2️⃣ Systemd Service

Unit file location: /etc/systemd/system/couchdb.service

[Unit]
Description=Apache CouchDB
After=network.target

[Service]
Type=simple                     # Track main process directly
User=couchdb                     # Run as couchdb user
ExecStart=/opt/couchdb/bin/couchdb   # no -b (foreground)
ExecStop=/opt/couchdb/bin/couchdb -k
Restart=on-failure
LimitNOFILE=65536
TimeoutStartSec=300              # Give enough time for CouchDB to start

[Install]
WantedBy=multi-user.target


Type=simple avoids “activating → timeout” issues

Systemd will restart only on failure

Can check status: sudo systemctl status couchdb

Start/stop/restart: sudo systemctl start/stop/restart couchdb

3️⃣ Configuration (local.ini)

File: /opt/couchdb/etc/local.ini

[chttpd]
port = 5984
bind_address = 127.0.0.1     ; localhost-only


CouchDB listens only on localhost (safe for local apps)

Default port is 5984

Other sections mostly default; keep changes in local.ini, never modify default.ini

4️⃣ Permissions
sudo chown -R couchdb:couchdb /opt/couchdb
sudo chmod -R 0755 /opt/couchdb


CouchDB must own its directories (bin, etc, var, log)

Prevents startup failures and systemd timeout loops

5️⃣ Checking CouchDB

Is it listening?

sudo ss -tlnp | grep 5984


Check readiness (localhost)

curl -s http://127.0.0.1:5984/ | grep couchdb && echo "CouchDB ready" || echo "Not ready yet"


Loop until ready:

while ! curl -s http://127.0.0.1:5984/ | grep -q couchdb; do sleep 2; done; echo "CouchDB ready!"

6️⃣ Logs
sudo journalctl -u couchdb -f


Watch startup messages

Check for DNS or port errors if startup is slow

7️⃣ Troubleshooting

Stuck in activating → systemd waiting for forked process: solved by Type=simple + no -b

Port conflicts → check ss -tlnp | grep 5984

Permissions issues → ensure couchdb:couchdb ownership for /opt/couchdb

Timeout → increase TimeoutStartSec if using Type=forking

8️⃣ Tips

Use curl locally to check service instead of staring at systemctl status

Keep local.ini as main config; changes in default.ini may be overwritten on upgrade

For automation scripts, use the “readiness one-liner” to ensure CouchDB is up before starting dependent apps