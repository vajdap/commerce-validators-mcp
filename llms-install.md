# Installing Commerce Validators (for AI agents)

The easiest install is the **hosted remote server** — no build, no env vars, no keys
for the free tools.

## Remote (recommended)

Add to the MCP client config:

```json
{ "mcpServers": { "commerce-validators": { "url": "https://mcp.scienceswarm.org/mcp" } } }
```

Transport: Streamable HTTP. 10 tools are discovered dynamically via `tools/list`.

The 7 free tools (IBAN / ABA / GTIN checksums, EU VAT rates, Stripe Connect split,
payout reconciliation, reorder point) work immediately. The 3 live-registry tools
(EU VAT via VIES, EORI via EU customs, email/MX) need a one-time $9 Pro key (launch pricing) from
<https://ops.scienceswarm.org/mcp>; then use:

```json
{ "mcpServers": { "commerce-validators": { "url": "https://mcp.scienceswarm.org/mcp?key=YOUR_KEY" } } }
```

Keyless calls to gated tools return a structured JSON upsell (never an exception), so
agents can handle it gracefully.

## Local (stdio, all tools free)

```bash
pip install mcp
python3 server.py
```

Client config:

```json
{ "mcpServers": { "commerce-validators": { "command": "python3", "args": ["/path/to/server.py"] } } }
```

No environment variables are required. `MCP_HTTP=1 MCP_PORT=8790` switches to
streamable-HTTP hosting; `MCP_HOST` overrides the bind address (default 127.0.0.1).

## Verify the install

Call `validate_gtin` with `{"code": "4006381333931"}` → `{"valid": true, ...}`.
