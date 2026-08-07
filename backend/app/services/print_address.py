"""Which of a customer's addresses a printed document should carry.

A customer holds three, and they are genuinely different places: the office
that signs the paperwork, the site the goods go to, and the address registered
for tax. Which one belongs on a document is not a property of the customer —
it is a decision made per document, at the moment it is printed. The same
customer takes delivery at a plant in Gresik and correspondence at a head
office in Jakarta, and a quotation for the plant should say so.

So the app asks, rather than guessing, and this module is the one place that
knows what there is to ask about. The customer PO sheet has worked this way
for a while; keeping the list and the resolution here is what stops the
quotation export from slowly growing a different idea of what "delivery"
means.

A key that resolves to nothing falls back to the office address rather than
printing an empty block. A document with the wrong heading is recoverable; a
document with no destination on it gets sent back.
"""

from __future__ import annotations

from dataclasses import dataclass

# key -> (English label, Indonesian label, Customer attribute)
ADDRESS_KINDS: list[tuple[str, str, str, str]] = [
    ("office",   "Office",           "Kantor",             "company_address"),
    ("delivery", "Delivery address", "Alamat Pengiriman",  "delivery_address"),
    ("tax",      "Tax address",      "Alamat Pajak",       "tax_address"),
]

VALID_KEYS = {k for k, _, _, _ in ADDRESS_KINDS}
DEFAULT_KEY = "office"


@dataclass
class ResolvedAddress:
    key: str
    label: str
    address: str
    fell_back: bool = False


def address_options(cust) -> list[dict]:
    """Every address this customer has, for the picker to offer.

    Kinds the customer has not filled in are still listed, greyed out by the
    caller — seeing that "Alamat Pengiriman" exists but is empty is how
    somebody learns to go and fill it in.
    """
    return [
        {
            "key": key,
            "label": en,
            "label_id": idn,
            "address": (getattr(cust, attr, None) or "") if cust else "",
        }
        for key, en, idn, attr in ADDRESS_KINDS
    ]


def resolve_address(cust, key: str | None) -> ResolvedAddress:
    """The label and text to print, honouring the request where it can."""
    key = (key or DEFAULT_KEY).strip().lower()
    if key not in VALID_KEYS:
        key = DEFAULT_KEY

    chosen = next(k for k in ADDRESS_KINDS if k[0] == key)
    text = (getattr(cust, chosen[3], None) or "") if cust else ""
    if text:
        return ResolvedAddress(key=key, label=chosen[2], address=text)

    office = (getattr(cust, "company_address", None) or "") if cust else ""
    if office:
        return ResolvedAddress(key="office", label="Kantor", address=office,
                               fell_back=True)
    return ResolvedAddress(key=key, label=chosen[2], address="—", fell_back=True)


def contact_options(cust, contacts) -> list[dict]:
    """The people the document could be addressed to.

    The customer record carries a primary PIC of its own, separate from the
    contacts table, so it is listed first and without an id — the caller sends
    no `contact_id` to choose it.
    """
    out: list[dict] = []
    if cust and cust.pic_name:
        out.append({
            "id": None, "name": cust.pic_name,
            "position": cust.pic_position or "", "phone": cust.phone or "",
            "email": cust.email or "", "primary": True,
        })
    for ct in contacts:
        out.append({
            "id": str(ct.id), "name": ct.name, "position": ct.position or "",
            "phone": ct.phone or "", "email": ct.email or "",
            "primary": bool(ct.is_primary),
        })
    return out
