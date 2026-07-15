#!/usr/bin/env python3
"""
Ecommerce Ops Tools — MCP server (Peter Inc, openly AI-operated).

Exposes correct, tested ecommerce/finance calculations as MCP tools an AI agent can
call while doing Shopify/Stripe/marketplace work — so the agent doesn't re-derive
fiddly money math (Stripe Connect three-way splits, payout reconciliation, reorder
points) and get it subtly wrong. The logic is ported from our verified web calculators
(each adversarially tested).

Self-hosted: every tool is free (no gating). On our hosted endpoint
(https://mcp.scienceswarm.org/mcp) the live-registry lookups need a Pro key
(MCP_PRO_GATE=1 there) — https://ops.scienceswarm.org/mcp.

Run (stdio, for local agents / registry testing):
    python3 mcp-server/server.py

Depends only on the `mcp` SDK.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("commerce-validators", host=os.environ.get("MCP_HOST", "127.0.0.1"),
              port=int(os.environ.get("MCP_PORT", "8790")))

UA = {"User-Agent": "commerce-validators-mcp/1.0 (+https://github.com/vajdap/commerce-validators-mcp)"}


def _get(url: str, timeout: int = 15):
    """GET with our UA (default Python-urllib UA is bot-blocked by some services)."""
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)

# ---- freemium: live-lookup tools (real external cost/value) need a Pro key ----
import contextvars

KEYSTORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".keys.json")
PRO_URL = "https://ops.scienceswarm.org/mcp"
_current_key = contextvars.ContextVar("api_key", default=None)


def _valid_key(k: str | None) -> bool:
    if not k:
        return False
    try:
        data = json.load(open(KEYSTORE))
        keys = data if isinstance(data, list) else data.get("keys", [])
        import hmac
        return any(hmac.compare_digest(k, x) for x in keys if isinstance(x, str))
    except Exception:
        return False


def _pro_gate():
    """None if gating is off or the caller has a valid Pro key; else an upsell dict.

    Gating is enabled only on our hosted endpoint (MCP_PRO_GATE=1). Self-hosted
    copies are fully functional with every tool free — the hosted convenience
    (zero setup, always on) is what the Pro key pays for."""
    if os.environ.get("MCP_PRO_GATE", "").lower() in ("", "0", "false", "no", "off"):
        return None
    if _valid_key(_current_key.get()):
        return None
    return {"pro_required": True,
            "message": "This tool performs a live external lookup and needs a Pro key.",
            "get_a_key": PRO_URL,
            "then": "set your MCP server URL to https://mcp.scienceswarm.org/mcp?key=YOUR_KEY"}


# ---- free-substitute-RESISTANT tools: real lookups / fiddly validators an LLM can't fake ----

def _validate_eu_vat_blocking(vat_number: str) -> dict:
    """Validate an EU VAT number against the official EU VIES service (live government
    lookup). Returns whether it is registered/valid and, if available, the registered
    trader name + address. An LLM cannot know this without the real lookup — use this
    before invoicing/reverse-charging an EU B2B customer. Input e.g. 'DE811569869' or
    'IE6388047V' (country code + number).
    """
    v = re.sub(r"[\s\-\.]", "", vat_number or "").upper()
    m = re.match(r"^([A-Z]{2})([A-Z0-9]{2,12})$", v)
    if not m:
        return {"input": vat_number, "valid": False,
                "error": "bad format — need country code + 2-12 alphanumeric characters"}
    cc, num = m.group(1), m.group(2)
    url = f"https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{num}"
    try:
        with _get(url) as r:
            d = json.loads(r.read())
        # userError values like MS_UNAVAILABLE / TIMEOUT mean "no answer", NOT "invalid"
        err = (d.get("userError") or "").upper()
        if err and err not in ("VALID", "INVALID"):
            return {"input": vat_number, "valid": None,
                    "error": f"VIES could not answer ({err}) — the member state's service "
                             "may be down; retry later.", "source": "EU VIES"}
        def _clean(x):
            return None if x in (None, "", "---") else x
        return {"input": vat_number, "country": cc, "vat_number": num,
                "valid": bool(d.get("isValid")), "name": _clean(d.get("name")),
                "address": _clean(d.get("address")), "source": "EU VIES"}
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


def _check_email_domain_blocking(email_or_domain: str) -> dict:
    """Check whether a domain can actually receive email (has MX records) via a real
    DNS-over-HTTPS lookup — validate a customer/supplier email's domain before sending
    or invoicing. An LLM can't know current DNS; this does the live lookup."""
    x = (email_or_domain or "").strip().lower()
    domain = x.split("@")[-1]
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
        return {"input": email_or_domain, "valid_domain": False, "reason": "bad domain format"}
    try:
        url = "https://dns.google/resolve?" + urllib.parse.urlencode({"name": domain, "type": "MX"})
        with _get(url, timeout=10) as r:
            d = json.loads(r.read())
        mx = [a["data"] for a in d.get("Answer", []) if a.get("type") == 15]
        return {"input": email_or_domain, "domain": domain,
                "can_receive_email": bool(mx), "mx_records": mx[:5], "source": "DNS/MX"}
    except Exception as e:
        return {"input": email_or_domain, "domain": domain, "can_receive_email": None,
                "error": f"DNS lookup failed ({e})"}


def _validate_eori_blocking(eori: str) -> dict:
    """Validate an EORI number (Economic Operators Registration and Identification)
    against the official EU customs database (live lookup). An EORI is required for
    EU imports/exports — check a trading partner's or your own EORI before customs
    filings / freight bookings. Input e.g. 'DE1234567890123' (country code + number).
    """
    e = re.sub(r"[\s\-\.]", "", eori or "").upper()
    if not re.match(r"^[A-Z]{2}[A-Z0-9]{1,15}$", e):
        return {"input": eori, "valid": False, "error": "bad format — 2-letter country code + identifier"}
    soap = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:eor="http://eori.ws.eos.dds.s/"><soapenv:Body>'
            f'<eor:validateEORI><eor:eori>{e}</eor:eori></eor:validateEORI>'
            '</soapenv:Body></soapenv:Envelope>')
    try:
        req = urllib.request.Request(
            "https://ec.europa.eu/taxation_customs/dds2/eos/validation/services/validation",
            data=soap.encode(), headers={"Content-Type": "text/xml; charset=utf-8", **UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        status = re.search(r"<status>(\d+)</status>", body)
        descr = re.search(r"<statusDescr>([^<]*)</statusDescr>", body)
        name = re.search(r"<name>([^<]*)</name>", body)
        if not status:
            return {"input": eori, "valid": None, "error": "unexpected EOS response", "source": "EU EOS"}
        import html
        return {"input": eori, "eori": e, "valid": status.group(1) == "0",
                "status_description": html.unescape(descr.group(1)) if descr else None,
                "registered_name": (html.unescape(name.group(1)) or None) if name else None,
                "source": "EU EOS (official customs registry)"}
    except Exception as ex:
        return {"input": eori, "valid": None,
                "error": f"EOS lookup unavailable ({ex}); retry later.", "source": "EU EOS"}


_VAT_RATES_CACHE: dict = {"at": 0.0, "data": None}
VAT_RATES_URL = "https://raw.githubusercontent.com/ibericode/vat-rates/master/vat-rates.json"


def _vat_rate_by_country_blocking(country_code: str, date: str = "") -> dict:
    """EU VAT rates (standard / reduced / super-reduced / parking) for a country,
    from the maintained ibericode/vat-rates dataset (fetched live, cached 24h) —
    including which rate set was in force on an optional 'date' (YYYY-MM-DD) and the
    names of regional exceptions (e.g. Canary Islands). Input e.g. 'DE', 'FR', 'HU'.
    """
    import time
    cc = (country_code or "").strip().upper()
    if not re.match(r"^[A-Z]{2}$", cc):
        return {"input": country_code, "error": "need a 2-letter country code, e.g. 'DE'"}
    when = (date or "").strip() or time.strftime("%Y-%m-%d")
    try:
        import datetime as _dt
        _dt.date.fromisoformat(when)
    except ValueError:
        return {"input": country_code, "error": "date must be a real calendar date, YYYY-MM-DD"}
    try:
        if not _VAT_RATES_CACHE["data"] or time.time() - _VAT_RATES_CACHE["at"] > 86400:
            with _get(VAT_RATES_URL) as r:
                _VAT_RATES_CACHE["data"] = json.load(r)
                _VAT_RATES_CACHE["at"] = time.time()
    except Exception as ex:
        if not _VAT_RATES_CACHE["data"]:
            return {"input": country_code, "error": f"rates dataset unavailable ({ex}); retry later."}
    periods = (_VAT_RATES_CACHE["data"].get("items") or {}).get(cc)
    if not isinstance(periods, list) or not periods:
        return {"input": country_code, "found": False,
                "note": "dataset covers EU member states (plus GB pre-Brexit history)"}
    applicable = [p for p in periods if isinstance(p, dict)
                  and isinstance(p.get("effective_from"), str) and p["effective_from"] <= when]
    if not applicable:
        return {"input": country_code, "found": False, "note": f"no rate set in force on {when}"}
    chosen = max(applicable, key=lambda p: p["effective_from"])
    out = {"country": cc, "as_of": when,
           "rates_pct": chosen.get("rates", {}),
           "effective_from": chosen.get("effective_from"),
           "regional_exceptions": [x.get("name") for x in chosen.get("exceptions", [])
                                   if isinstance(x, dict)],
           "source": "ibericode/vat-rates (community-maintained; confirm with a tax advisor for filings)"}
    if cc == "GB":
        out["note"] = "the UK left the EU VAT system in 2021 — GB data may not be maintained"
    elif when < "2000-01-01":
        out["note"] = "historical coverage is limited; treat pre-2000 answers as unreliable"
    return out



# Async shims: lookups run in a worker thread so one tenant's slow/timed-out external
# call can't stall the event loop (and every other session) in hosted HTTP mode.

@mcp.tool()
async def validate_eu_vat(vat_number: str) -> dict:
    """Validate an EU VAT number against the official EU VIES service (live government
    lookup). Returns whether it is registered/valid and, if available, the registered
    trader name + address. An LLM cannot know this without the real lookup — use this
    before invoicing/reverse-charging an EU B2B customer. Input e.g. 'DE811569869' or
    'IE6388047V' (country code + number).
    """
    gate = _pro_gate()
    if gate:
        return gate
    return await asyncio.to_thread(_validate_eu_vat_blocking, vat_number)


@mcp.tool()
async def validate_eori(eori: str) -> dict:
    """Validate an EORI number (Economic Operators Registration and Identification)
    against the official EU customs database (live lookup). An EORI is required for
    EU imports/exports — check a trading partner's or your own EORI before customs
    filings / freight bookings. Input e.g. 'DE1234567890123' (country code + number).
    """
    gate = _pro_gate()
    if gate:
        return gate
    return await asyncio.to_thread(_validate_eori_blocking, eori)


@mcp.tool()
async def check_email_domain(email_or_domain: str) -> dict:
    """Check whether a domain can actually receive email (has MX records) via a real
    DNS-over-HTTPS lookup — validate a customer/supplier email's domain before sending
    or invoicing. An LLM can't know current DNS; this does the live lookup."""
    gate = _pro_gate()
    if gate:
        return gate
    return await asyncio.to_thread(_check_email_domain_blocking, email_or_domain)


@mcp.tool()
async def vat_rate_by_country(country_code: str, date: str = "") -> dict:
    """EU VAT rates (standard / reduced / super-reduced / parking) for a country,
    from the maintained ibericode/vat-rates dataset (fetched live, cached 24h) —
    including which rate set was in force on an optional 'date' (YYYY-MM-DD) and the
    names of regional exceptions (e.g. Canary Islands). Input e.g. 'DE', 'FR', 'HU'.
    """
    return await asyncio.to_thread(_vat_rate_by_country_blocking, country_code, date)


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
    if fee_bearer not in ("seller", "platform", "buyer"):
        return {"error": f"fee_bearer must be 'seller', 'platform' or 'buyer' (got {fee_bearer!r})"}
    if not (0 <= processing_pct < 100) or processing_fixed < 0 or \
            application_fee_pct < 0 or application_fee_fixed < 0:
        return {"error": "fees must be non-negative and processing_pct < 100"}
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
    # MCP_HTTP=1 -> remote streamable-HTTP (for hosting) with a Pro-key ASGI middleware
    # that reads ?key= from the URL and exposes it to the Pro-gated tools; else stdio.
    if os.environ.get("MCP_HTTP"):
        import uvicorn
        from urllib.parse import parse_qs

        inner = mcp.streamable_http_app()

        async def key_mw(scope, receive, send):
            if scope.get("type") == "http":
                key = parse_qs(scope.get("query_string", b"").decode()).get("key", [None])[0]
                _current_key.set(key)
            await inner(scope, receive, send)

        uvicorn.run(key_mw, host=os.environ.get("MCP_HOST", "127.0.0.1"),
                    port=int(os.environ.get("MCP_PORT", "8790")))
    else:
        mcp.run()
