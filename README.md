# Commerce Validators — MCP server

Real validation + lookups for ecommerce / fintech agent workflows — the checks an LLM
**can't reliably do itself** (live registry lookups, fiddly checksums). Built and run by
**Peter Inc**, an openly AI-operated studio (a human owner, Peter Vajda, is accountable).

## Connect (hosted, remote — Streamable HTTP)

```
https://mcp.scienceswarm.org/mcp
```

Example (Claude Desktop / Cursor / any MCP client, remote server config):
```json
{ "mcpServers": { "commerce-validators": { "url": "https://mcp.scienceswarm.org/mcp" } } }
```

## Tools

| Tool | What it does | Why an agent needs it |
|---|---|---|
| `validate_eu_vat` | Live **EU VIES** lookup — is a VAT number registered? returns trader name+address | An LLM can't know a government registry; required before EU B2B invoicing / reverse-charge |
| `check_email_domain` | Live **DNS/MX** lookup — can this domain receive email? | Validate a customer/supplier email domain before sending or invoicing |
| `validate_iban` | ISO-7064 **mod-97** + country length | Catch a mistyped bank account before a transfer |
| `validate_aba_routing` | US **ABA** routing-number checksum | Catch a bad routing number before an ACH/wire |
| `validate_gtin` | **GTIN-8/12/13/14** barcode check digit | Catch mistyped product barcodes in catalog/inventory |
| `stripe_connect_split` | Stripe Connect three-way fee split (buyer/Stripe/platform/seller) | Correct marketplace take-rate math |
| `payout_reconciliation` | Gross → deductions → expected payout, flags the unexplained gap | Explain a short payout |
| `reorder_point` | Lead-time demand + safety stock; reorder-now verdict | Inventory timing |

All tools return structured JSON. VIES / DNS lookups are live (VIES is periodically down —
handled gracefully). Rates in the finance tools are editable; verify against your own
agreements. No secrets or customer data are stored.

## Self-host (stdio)
```
pip install mcp
MCP_HTTP=1 MCP_PORT=8790 python3 server.py     # remote HTTP
python3 server.py                              # local stdio
```
