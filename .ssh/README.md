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

**Settings page auto-detection**: the SSH Key picker under Oracle Cloud
Integration only looks for the **public** half - a file ending in `.pub`
(this is the key Oracle injects into a new VM, not the one you use to
SSH into it). It has nothing to do with the private-key filename above;
place both if you have them:

```bash
.ssh/oracle.key       # private - yours, for `ssh -i`, ignored by the picker
.ssh/oracle.pub       # public - shows up in the Settings page as "oracle"
```

If you don't have a `.pub` file yet, generate one from an existing
private key with `ssh-keygen -y -f .ssh/oracle.key > .ssh/oracle.pub`.
