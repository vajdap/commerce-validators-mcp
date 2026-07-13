#!/usr/bin/env python3
"""
Ecommerce Ops Tools — MCP server (Peter Inc, openly AI-operated).

Exposes correct, tested ecommerce/finance calculations as MCP tools an AI agent can
call while doing Shopify/Stripe/marketplace work — so the agent doesn't re-derive
fiddly money math (Stripe Connect three-way splits, payout reconciliation, reorder
points) and get it subtly wrong. The logic is ported from our verified web calculators
(each adversarially tested). Free to try; a paid tier gates volume/premium tools
(billing wired separately — Stripe MPP / x402).

Run (stdio, for local agents / registry testing):
    python3 mcp-server/server.py

Depends only on the `mcp` SDK.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("commerce-validators", host="0.0.0.0",
              port=int(os.environ.get("MCP_PORT", "8790")))


# ---- free-substitute-RESISTANT tools: real lookups / fiddly validators an LLM can't fake ----

@mcp.tool()
def validate_eu_vat(vat_number: str) -> dict:
    """Validate an EU VAT number against the official EU VIES service (live government
    lookup). Returns whether it is registered/valid and, if available, the registered
    trader name + address. An LLM cannot know this without the real lookup — use this
    before invoicing/reverse-charging an EU B2B customer. Input e.g. 'DE811569869' or
    'IE6388047V' (country code + number).
    """
    v = re.sub(r"[\s\-\.]", "", vat_number or "").upper()
    m = re.match(r"^([A-Z]{2})(.+)$", v)
    if not m:
        return {"input": vat_number, "valid": False, "error": "bad format — need country code + number"}
    cc, num = m.group(1), m.group(2)
    url = f"https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{num}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.loads(r.read())
        return {"input": vat_number, "country": cc, "vat_number": num,
                "valid": bool(d.get("valid")), "name": d.get("name"),
                "address": d.get("address"), "source": "EU VIES"}
    except Exception as e:
        return {"input": vat_number, "valid": None,
                "error": f"VIES lookup unavailable ({e}); VIES is periodically down — retry later.",
                "source": "EU VIES"}


@mcp.tool()
def validate_iban(iban: str) -> dict:
    """Validate an IBAN (International Bank Account Number) by structure + the ISO 7064
    mod-97 checksum. Catches typos/invalid accounts before you initiate a transfer.
    Pure-algorithm; no data leaves the machine."""
    s = re.sub(r"\s", "", iban or "").upper()
    if not re.match(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$", s):
        return {"input": iban, "valid": False, "reason": "invalid IBAN format"}
    LEN = {"DE": 22, "FR": 27, "GB": 22, "NL": 18, "ES": 24, "IT": 27, "IE": 22,
           "BE": 16, "AT": 20, "CH": 21, "PL": 28, "PT": 25, "SE": 24, "NO": 15}
    exp = LEN.get(s[:2])
    if exp and len(s) != exp:
        return {"input": iban, "valid": False, "reason": f"wrong length for {s[:2]} (expected {exp}, got {len(s)})"}
    rearr = s[4:] + s[:4]
    num = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearr)
    ok = int(num) % 97 == 1
    return {"input": iban, "valid": ok, "country": s[:2],
            "reason": "checksum ok" if ok else "mod-97 checksum failed"}


@mcp.tool()
def validate_gtin(code: str) -> dict:
    """Validate a GTIN / UPC / EAN barcode (GTIN-8/12/13/14) by its check digit.
    Catches mistyped product barcodes in inventory/catalog workflows. Pure-algorithm."""
    c = re.sub(r"\s", "", code or "")
    if not c.isdigit() or len(c) not in (8, 12, 13, 14):
        return {"input": code, "valid": False, "reason": "must be 8, 12, 13, or 14 digits"}
    body, check = [int(d) for d in c[:-1]], int(c[-1])
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    calc = (10 - total % 10) % 10
    return {"input": code, "valid": calc == check, "type": f"GTIN-{len(c)}",
            "expected_check_digit": calc}


@mcp.tool()
def validate_aba_routing(routing_number: str) -> dict:
    """Validate a US ABA bank routing number (9 digits) by its checksum. Catch typos
    before initiating an ACH/wire payout. Pure-algorithm; nothing leaves the machine."""
    r = re.sub(r"\D", "", routing_number or "")
    if len(r) != 9:
        return {"input": routing_number, "valid": False, "reason": "must be 9 digits"}
    d = [int(c) for c in r]
    chk = (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10
    return {"input": routing_number, "valid": chk == 0,
            "reason": "checksum ok" if chk == 0 else "ABA checksum failed"}


@mcp.tool()
def check_email_domain(email_or_domain: str) -> dict:
    """Check whether a domain can actually receive email (has MX records) via a real
    DNS-over-HTTPS lookup — validate a customer/supplier email's domain before sending
    or invoicing. An LLM can't know current DNS; this does the live lookup."""
    x = (email_or_domain or "").strip().lower()
    domain = x.split("@")[-1]
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
        return {"input": email_or_domain, "valid_domain": False, "reason": "bad domain format"}
    try:
        url = "https://dns.google/resolve?" + urllib.parse.urlencode({"name": domain, "type": "MX"})
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read())
        mx = [a["data"] for a in d.get("Answer", []) if a.get("type") == 15]
        return {"input": email_or_domain, "domain": domain,
                "can_receive_email": bool(mx), "mx_records": mx[:5], "source": "DNS/MX"}
    except Exception as e:
        return {"input": email_or_domain, "domain": domain, "can_receive_email": None,
                "error": f"DNS lookup failed ({e})"}


@mcp.tool()
def stripe_connect_split(charge_amount: float, application_fee_pct: float = 0.0,
                         application_fee_fixed: float = 0.0,
                         processing_pct: float = 2.9, processing_fixed: float = 0.30,
                         fee_bearer: str = "seller") -> dict:
    """Compute the Stripe Connect three-way split for one charge.

    Returns what the buyer pays, what Stripe takes, what the platform nets (its
    application fee), and what the connected seller nets — plus the platform's
    effective take rate. fee_bearer: 'seller' | 'platform' | 'buyer' (who absorbs the
    Stripe processing fee). Rates are editable; defaults are US card standard 2.9%+$0.30.
    """
    c = max(0.0, charge_amount)
    stripe_fee = round(c * processing_pct / 100 + processing_fixed, 2)
    app_fee = round(c * application_fee_pct / 100 + application_fee_fixed, 2)
    buyer_pays = c
    if fee_bearer == "buyer":
        # gross up so buyer covers the processing fee; platform+seller split the intended amount
        buyer_pays = round((c + processing_fixed) / (1 - processing_pct / 100), 2)
        stripe_fee = round(buyer_pays * processing_pct / 100 + processing_fixed, 2)
        platform_net = app_fee
        seller_net = round(c - app_fee, 2)
    elif fee_bearer == "platform":
        platform_net = round(app_fee - stripe_fee, 2)
        seller_net = round(c - app_fee, 2)
    else:  # seller bears the Stripe fee (direct-charge default)
        platform_net = app_fee
        seller_net = round(c - app_fee - stripe_fee, 2)
    take_rate = round((platform_net / c * 100) if c else 0.0, 2)
    return {"buyer_pays": buyer_pays, "stripe_fee": stripe_fee,
            "platform_net": platform_net, "seller_net": seller_net,
            "platform_take_rate_pct": take_rate,
            "note": "Rates approximate; verify against your Stripe agreement."}


@mcp.tool()
def payout_reconciliation(gross_sales: float, refunds: float = 0.0,
                          processing_fees: float = 0.0, chargebacks: float = 0.0,
                          other_deductions: float = 0.0,
                          actual_deposit: float | None = None) -> dict:
    """Explain why a payout is less than sales: walk gross -> deductions -> expected,
    and (if actual_deposit given) flag the unexplained gap (shortfall/surplus)."""
    expected = round(gross_sales - refunds - processing_fees - chargebacks - other_deductions, 2)
    out = {"gross_sales": round(gross_sales, 2), "total_deductions":
           round(refunds + processing_fees + chargebacks + other_deductions, 2),
           "expected_payout": expected}
    if actual_deposit is not None:
        gap = round(actual_deposit - expected, 2)
        out["actual_deposit"] = round(actual_deposit, 2)
        out["unexplained_gap"] = gap
        out["verdict"] = ("matches" if abs(gap) < 0.01 else
                          f"shortfall of {abs(gap):.2f}" if gap < 0 else
                          f"surplus of {gap:.2f}")
    return out


@mcp.tool()
def reorder_point(avg_daily_sales: float, lead_time_days: float,
                  safety_stock: float = 0.0, on_hand: float | None = None) -> dict:
    """Reorder point = lead-time demand + safety stock. If on_hand is given, returns
    whether to reorder now and the days of cover remaining."""
    ltd = round(avg_daily_sales * lead_time_days, 2)
    rop = round(ltd + safety_stock, 2)
    out = {"lead_time_demand": ltd, "safety_stock": round(safety_stock, 2),
           "reorder_point": rop}
    if on_hand is not None:
        out["on_hand"] = round(on_hand, 2)
        out["reorder_now"] = on_hand <= rop
        out["days_of_cover"] = round(on_hand / avg_daily_sales, 1) if avg_daily_sales else None
    return out


if __name__ == "__main__":
    # MCP_HTTP=1 -> remote streamable-HTTP transport (for hosting); else local stdio.
    if os.environ.get("MCP_HTTP"):
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
