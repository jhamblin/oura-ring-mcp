# Security

## Your Personal Access Token

Your Oura PAT grants full **read** access to your complete biometric history. Treat it with the same care as a password.

- **Get a token**: [cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens)
- **Set it safely**: environment variable `OURA_PAT` or `~/.oura-mcp/config.json` — never in source code
- **Revoke it**: cloud.ouraring.com → Personal Access Tokens → delete

`oura-mcp` never logs your token. A redaction filter is installed at startup on the `httpx` and `httpcore` loggers that strips `Authorization:` headers from any debug output.

## Reporting a vulnerability

If you discover a security issue in `oura-mcp` (token leak, path traversal in cache, etc.), please report it privately:

- **Email**: open a GitHub Security Advisory instead of a public issue
- **GitHub**: Repository → Security → "Report a vulnerability"

Please include:
- A description of the issue and potential impact
- Steps to reproduce
- Suggested fix if you have one

We will respond within 72 hours and aim to release a fix within 7 days for critical issues.

## Accidentally committed a token

If a real PAT is committed to a public or private repository:

**1. Revoke it immediately** — go to [cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens) and delete the token. A simple delete-and-re-commit leaves the token in git history forever; revoke first.

**2. Generate a new token** on the Oura dashboard.

**3. Purge the token from history** using `git filter-repo`:

```bash
pip install git-filter-repo

git filter-repo --replace-text <(echo "OLD_TOKEN_VALUE==>REDACTED")
```

**4. Force-push** (this rewrites history — coordinate with collaborators):

```bash
git push --force-with-lease origin main
```

**5. Rotate any downstream config** that used the old token (Claude Desktop, CI secrets, etc.).

> `git rm` and `git commit` do **not** remove a token from history. The purge step is mandatory.

## Cache file security

If `OURA_MCP_CACHE_DIR` is set, per-day JSON files are written to that directory. These files contain biometric data (sleep sessions, HRV, SpO2). Ensure the directory has appropriate permissions:

```bash
chmod 700 ~/.oura-mcp/raw
```

The cache directory is never committed to the repository (it is listed in `.gitignore`).
