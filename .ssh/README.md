# SSH keys go here

A convenient place to keep the SSH private/public key pairs you use to
connect to your VPS boxes (e.g. a region VPS), so they're kept alongside
this project instead of scattered under `~/.ssh/` with names you have to
remember separately.

**Everything in this folder except this README is gitignored** - real key
material placed here is never committed, no matter what.

Example:

```bash
# after downloading a key from your VPS provider
mv ~/Downloads/ssh-key-2026-08-04.key .ssh/oracle.key
chmod 600 .ssh/oracle.key

ssh -i .ssh/oracle.key ubuntu@<your-vps-ip>
```
