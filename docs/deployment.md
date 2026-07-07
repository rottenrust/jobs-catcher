# Deployment

Default paths: `/opt/jobs-catcher`, `/var/lib/jobs-catcher`, `/var/lib/jobs-catcher/uploads`, `/var/lib/jobs-catcher/runs`, `/etc/jobs-catcher.env`. Runtime user: `jobscatcher`. Install: `scripts/install.sh`. Update: `scripts/update.sh`. Logs: `journalctl -u jobs-catcher-web -f` and `journalctl -u jobs-catcher-worker -f`. HTTPS: issue certificates with certbot or another ACME client, then add TLS server block and set production cookies Secure. Rollback: stop services, checkout previous release, install, restore DB backup if needed, start services.
