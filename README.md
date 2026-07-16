# Commerce Validators — MCP server

Real validation + live registry lookups for ecommerce / fintech agent workflows — the
checks an LLM **can't reliably do itself** (live government registries, fiddly checksums).
Built and run by **Peter Inc**, an openly AI-operated studio (a human owner, Peter Vajda,
is accountable).

## Connect (hosted, remote — Streamable HTTP)

```
https://mcp.scienceswarm.org/mcp
```

```json
{ "mcpServers": { "commerce-validators": { "url": "https://mcp.scienceswarm.org/mcp" } } }
```

On the hosted endpoint the three **live-registry tools** (EU VAT, EORI, email/MX) need a
Pro key — **$9 one-time (launch pricing; list $19)** at <https://ops.scienceswarm.org/mcp>, then connect with
`https://mcp.scienceswarm.org/mcp?key=YOUR_KEY`. Everything else is free, no key, no
account.

**Self-hosting this repo is completely free — every tool, no gating, no key.** The Pro
key pays for the hosted convenience (zero setup, always on), not the code.

## Tools

| Tool | What it does | Hosted tier |
|---|---|---|
| `validate_eu_vat` | Live **EU VIES** lookup — is a VAT number registered? returns trader name+address | Pro |
| `validate_eori` | Live **EU customs (EOS)** lookup — is an EORI number valid? Required for EU imports/exports | Pro |
| `check_email_domain` | Live **DNS/MX** lookup — can this domain receive email? | Pro |
| `vat_rate_by_country` | EU VAT rates (standard/reduced/…) in force on a date, incl. regional exceptions | Free |
| `validate_iban` | ISO-7064 **mod-97** + country length | Free |
| `validate_aba_routing` | US **ABA** routing-number checksum | Free |
| `validate_gtin` | **GTIN-8/12/13/14** barcode check digit | Free |
| `stripe_connect_split` | Stripe Connect three-way fee split (buyer/Stripe/platform/seller) | Free |
| `payout_reconciliation` | Gross → deductions → expected payout, flags the unexplained gap | Free |
| `reorder_point` | Lead-time demand + safety stock; reorder-now verdict | Free |

All tools return structured JSON. Registry lookups (VIES / EOS / DNS) are live —
transient upstream outages are reported gracefully, retry later. Rates in the finance
tools are editable; verify against your own agreements. No secrets or customer data are
stored.

## Plain REST API (same tools, same key)

Not using MCP? Every validator is also a plain `GET` endpoint:

```
https://mcp.scienceswarm.org/api/v1                      # index
/api/v1/validate/iban/DE89370400440532013000             # free
/api/v1/validate/gtin/4006381333931                      # free
/api/v1/validate/routing/021000021                       # free
/api/v1/vat-rate/DE?date=2026-07-01                      # free
/api/v1/validate/vat/IE6388047V?key=YOUR_KEY             # Pro (live VIES)
/api/v1/validate/eori/DE1234567890?key=YOUR_KEY          # Pro (live EU customs)
/api/v1/validate/email/example.com?key=YOUR_KEY          # Pro (live DNS/MX)
```

Comparable VAT-validation APIs start at $15/month; the Pro key here is one-time.

## Self-host

```bash
pip install mcp
python3 server.py                              # local stdio — all tools free
MCP_HTTP=1 MCP_PORT=8790 python3 server.py     # remote streamable HTTP
```

Or with Docker:

```bash
docker build -t commerce-validators .
docker run -i commerce-validators
```

MIT licensed.
