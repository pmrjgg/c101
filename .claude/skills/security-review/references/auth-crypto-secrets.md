# Authentication, authorization, cryptography and secrets

## Authorization review procedure

1. Build the matrix: rows = endpoints/operations, columns = roles (anonymous, user, tenant admin, staff,
   service). Fill each cell from the code (decorators, middleware, policy calls), not from docs.
2. For each operation that takes an object identifier, find the query that loads it and check that the
   ownership/tenant predicate is part of the query (or a policy check runs on the loaded object before
   any use or response).
3. Check indirect object references: IDs inside JSON bodies, nested resources
   (`/orgs/{org}/projects/{project}`: is `project` checked to belong to `org`?), batch endpoints with
   ID lists, exports, search results, GraphQL nodes fetched by global ID, file download URLs.
4. Check that authorization happens on the server for every state change, including actions hidden in
   the UI and admin features reachable by URL.
5. Write a two-tenant (or two-user) test for each finding and for each critical operation reviewed.

```python
def test_project_not_readable_across_orgs(client, org_a_user, org_b_project):
    client.login(org_a_user)
    r = client.get(f"/orgs/{org_a_user.org_id}/projects/{org_b_project.id}")
    assert r.status_code == 404      # 404 avoids confirming existence; 403 is acceptable by policy
```

Common authorization defects:
- Check on the list endpoint but not on the detail endpoint (or the reverse).
- Check uses a client-supplied tenant ID instead of the session's tenant.
- Role checked by string comparison against a value the user can set (profile field, JWT claim minted
  by the client, header added by a proxy that clients can also send).
- Caching of authorized responses keyed without the user or tenant.
- Background jobs triggered by users run with system privileges on user-chosen objects.

## Authentication

- Password storage: Argon2id preferred. OWASP Password Storage Cheat Sheet minimums: Argon2id with
  19 MiB memory, 2 iterations, parallelism 1; scrypt N=2^17, r=8, p=1; bcrypt cost 10 (inputs truncated
  at 72 bytes; pre-hash carefully if longer passwords must be supported); PBKDF2-HMAC-SHA256 with 600,000
  iterations for FIPS contexts. Rehash on login when parameters are raised.
- Login: uniform responses and similar timing for unknown user vs wrong password; rate limiting per
  account and per IP; MFA for privileged accounts; WebAuthn/passkeys where possible.
- Password reset: tokens from a CSPRNG (>= 128 bits), stored hashed, single use, short expiry (15-60 min),
  invalidate sessions on reset, do not leak tokens via Referer (no third-party resources on the reset page).
- Sessions: random IDs >= 128 bits; rotate on login and privilege change; `Secure`, `HttpOnly`,
  `SameSite=Lax` or `Strict`; idle and absolute timeouts; server-side revocation.
- Remember-me and API tokens: hashed at rest, scoped, expiring, revocable, listed to the user.

## JWT checklist

- [ ] Verification pins the expected algorithm(s); library call does not accept `alg` from the token
      blindly (`none`, HS256 with an RSA public key as the secret).
- [ ] `exp` enforced with small leeway; `nbf`, `iat` sanity; `iss` and `aud` checked against config.
- [ ] Key selection by `kid` only from a trusted, configured JWKS; never fetch keys from URLs in the
      token header (`jku`, `x5u`).
- [ ] No sensitive data in the payload (it is only base64url-encoded).
- [ ] Revocation strategy: short-lived access tokens plus refresh tokens with rotation and reuse
      detection, or a denylist for high-risk events.
- [ ] Tokens not stored in `localStorage` when XSS risk is material (prefer `HttpOnly` cookies with CSRF
      defenses), and never put in URLs.

## OAuth 2.x / OIDC checklist

- [ ] Authorization code flow with PKCE for public clients (and recommended for all).
- [ ] `state` bound to the user session; `nonce` checked in ID tokens.
- [ ] Exact-match redirect URI registration; no wildcards or open redirects on the redirect target.
- [ ] Access token audience validated by resource servers.
- [ ] ID token signature, `iss`, `aud`, `exp` validated; do not use ID tokens as API access tokens.
- [ ] Scopes minimal; refresh tokens rotated and bound to client.
- [ ] Account linking by verified email only; beware providers that allow unverified emails.

## Webhooks and service-to-service

- Verify HMAC signatures over the raw body with constant-time comparison; include a timestamp in the
  signed content and reject old requests (replay window, e.g. 5 minutes); store processed event IDs for
  idempotency.
- mTLS or signed service tokens with audience; internal network location is not authentication.

## Cryptography review checklist

- [ ] High-level, maintained libraries (libsodium/PyNaCl, Tink, `cryptography` recipes like Fernet,
      `ring`/RustCrypto AEADs, Go `crypto/*`), not hand-assembled primitives.
- [ ] AEAD for encryption (AES-256-GCM, ChaCha20-Poly1305, XChaCha20-Poly1305); associated data used for
      context binding (record ID, version).
- [ ] Nonce strategy documented and unique per key; key rotation plan; keys separated by purpose (HKDF
      with distinct `info` labels).
- [ ] Randomness from the OS CSPRNG.
- [ ] Signatures: Ed25519 or ECDSA P-256 with deterministic nonces (RFC 6979) or library defaults; RSA
      >= 2048 bits with PSS for signatures and OAEP for encryption.
- [ ] Comparisons of secrets in constant time.
- [ ] TLS: certificate verification on; modern versions (TLS 1.2+, prefer 1.3); hostname verification on;
      no custom trust-all code paths, including in "test" modes that can ship.
- [ ] Hashing for integrity of untrusted data uses SHA-256 or better; MD5/SHA-1 only for non-security
      checksums, labelled as such.
- [ ] Post-quantum migration: note long-lived confidentiality needs (data that must stay secret for
      10+ years) where hybrid key exchange (e.g. X25519MLKEM768 in TLS) should be planned.

## Secrets handling

What to look for:
- Literal credentials: API keys, private keys (`-----BEGIN`), connection strings with passwords,
  cloud credentials, JWT signing secrets, webhook secrets.
- Secrets in `.env` files committed, Docker build args and layers, CI logs (`set -x`), test fixtures
  copied from production, mobile/web bundles, crash reports, analytics events.
- Overly broad secrets: one admin key shared by many services.

Reporting a secret:
```markdown
### [High] SEC-07 Stripe secret key committed in git history (CWE-798)
- Location: config/settings.py:12 at commit 3f2a9c1 (removed in 8b7d0e4, still in history)
- Type: payment provider secret key pattern (value not reproduced)
- Exposure: repository readable by 140 org members and CI logs; unknown external exposure
- Fix: rotate the key now (owner action); load from the secret manager; add gitleaks pre-commit and CI
  check; purge from history only after rotation (history rewriting does not revoke)
- Confidence: Confirmed (pattern and entropy match; not validated against the provider by design)
```

Never validate a found secret against its provider; that is use of a credential you are not
authorized to use.

## Logging and privacy

- Redact tokens, passwords, session IDs, full card numbers, government IDs in logs and traces.
- Avoid logging full request bodies on auth and payment endpoints.
- Retention and access controls on logs match the sensitivity of what they contain.
- Error responses: generic messages to clients, detailed errors with correlation IDs in server logs.
