"""How a company's name is written: in capitals, spaced once.

Company names are written the way they appear on a company's own letterhead
and tax papers — "PT JAKARTA PRIMA CRANE" — and the same company typed as
"PT Jakarta Prima CRANe" in one place and in capitals in another looked like
two companies and printed inconsistently. Enforced on the Customer and
Supplier models, so every way a name is written (forms, imports, edits)
arrives the same.
"""

import re


def company_name(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip().upper()
