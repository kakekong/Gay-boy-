"""Writing to the general journal, and what posting one does.

Everything that moves money should end up here eventually — a manual
correction, a bank payment, a depreciation run, an invoice. Today the older
single-entry postings (quotation, payment, salary) still write their own
`LedgerEntry` rows directly, so this module writes those rows too on the way
past. That is the bridge: the double-entry record becomes the truth, and
every report already built on `ledger_entries` keeps working untouched
rather than being rewritten in the same breath.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.journal import JournalEntry, JournalLine, signed_delta

# Rounded to the rupiah before comparing. A journal assembled from
# percentages — 11% PPN across five lines — lands fractions of a cent out,
# and refusing that would be arithmetic pedantry rather than bookkeeping.
TOLERANCE = 0.005


class JournalError(ValueError):
    """The entry cannot be written as given (unbalanced, empty, unknown account)."""


async def next_journal_number(db: AsyncSession) -> str:
    """JU-<YYYY>-<NNNN>. Jurnal Umum, the name the ledger goes by here."""
    from app.services.numbering import _next_suffix
    prefix = f"JU-{datetime.now(UTC):%Y}-"
    return f"{prefix}{await _next_suffix(db, JournalEntry.number, prefix):04d}"


def _money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


async def build_lines(db: AsyncSession, rows: list[dict]) -> list[JournalLine]:
    """Turn what somebody typed into journal lines, or refuse it.

    Each row names an account and puts an amount on one side of it. A line
    with both a debit and a credit is refused rather than netted: it means
    two things happened and the entry should say so as two lines, which is
    what makes the account history readable afterwards.
    """
    if not rows:
        raise JournalError("A journal entry needs at least two lines.")
    numbers = [str(r.get("account_no") or "").strip() for r in rows]
    if not all(numbers):
        raise JournalError("Every line needs an account.")
    found = {
        a.account_no: a for a in (await db.scalars(
            select(Account).where(Account.account_no.in_(numbers))
        )).all()
    }
    missing = sorted({n for n in numbers if n not in found})
    if missing:
        raise JournalError(f"Unknown account(s): {', '.join(missing)}")
    parents = sorted({n for n in numbers if found[n].is_parent})
    if parents:
        raise JournalError(
            "A heading can't carry a posting — it is the sum of what is under "
            f"it: {', '.join(parents)}"
        )
    suspended = sorted({n for n in numbers if found[n].is_suspended})
    if suspended:
        raise JournalError(f"Account suspended: {', '.join(suspended)}")

    lines: list[JournalLine] = []
    total_d = total_c = 0.0
    for i, r in enumerate(rows, 1):
        acc = found[str(r["account_no"]).strip()]
        debit, credit = _money(r.get("debit")), _money(r.get("credit"))
        if debit < 0 or credit < 0:
            raise JournalError(
                "A negative amount is the other side of the entry — put it in "
                "the other column."
            )
        if debit and credit:
            raise JournalError(
                f"Line {i} is both a debit and a credit. Two things happened; "
                "write them as two lines."
            )
        if not debit and not credit:
            raise JournalError(f"Line {i} has no amount.")
        total_d += debit
        total_c += credit
        lines.append(JournalLine(
            line_no=i, account_no=acc.account_no, account_type=acc.account_type,
            account_name=acc.name, debit=debit, credit=credit,
            memo=(r.get("memo") or None),
            customer_id=r.get("customer_id"), sales_pic_id=r.get("sales_pic_id"),
        ))
    if len(lines) < 2:
        raise JournalError(
            "An entry names both sides — what was debited and what was "
            "credited. One line is only half of it."
        )
    if abs(total_d - total_c) > TOLERANCE:
        raise JournalError(
            f"Debits and credits have to match: {total_d:,.2f} against "
            f"{total_c:,.2f}, out by {abs(total_d - total_c):,.2f}."
        )
    return lines


async def create_entry(
    db: AsyncSession, *,
    entry_date: date,
    rows: list[dict],
    memo: str | None = None,
    source_type: str = "manual",
    source_id: UUID | None = None,
    source_ref: str | None = None,
    created_by: UUID | None = None,
    post: bool = False,
    posted_by: UUID | None = None,
    back_fill: bool = False,
) -> JournalEntry:
    """Write a journal entry, optionally posting it in the same breath."""
    lines = await build_lines(db, rows)
    entry = JournalEntry(
        number=await next_journal_number(db),
        entry_date=entry_date, memo=memo,
        source_type=source_type, source_id=source_id, source_ref=source_ref,
        created_by=created_by, is_posted=False,
    )
    entry.lines = lines
    db.add(entry)
    await db.flush()
    if post:
        await post_entry(db, entry, actor_id=posted_by or created_by,
                         back_fill=back_fill)
    return entry


async def post_entry(db: AsyncSession, entry: JournalEntry,
                     *, actor_id: UUID | None = None,
                     back_fill: bool = False) -> JournalEntry:
    """Apply a journal to the accounts. Once, and never again.

    Each line moves its account's balance in the direction that account is
    normally read, and mirrors itself into the single-entry journal the
    existing reports are built on.

    `back_fill` is for one thing only: an entry that *records* history the
    balances already contain — the opening balances a chart of accounts
    arrives with. Those must not be applied again (the money is already in
    the balance) and must not reach the reporting journal (the profit report
    would count last year's trading as this month's). The entry exists so
    the account ledger can explain where a balance came from.
    """
    if entry.is_posted:
        return entry
    from app.services.ledger import journal_post as _single_entry_line

    for line in entry.lines:
        delta = signed_delta(line.account_type, line.debit, line.credit)
        if back_fill:
            continue
        acc = await db.scalar(
            select(Account).where(Account.account_no == line.account_no)
        )
        if acc is not None:
            acc.balance = float(acc.balance or 0) + delta
        # The bridge into the reporting journal. Cash & Bank lines carry the
        # money movement so cash reports stay a plain SUM.
        await _single_entry_line(
            db,
            entry_date=entry.entry_date,
            account_no=line.account_no,
            account_type=line.account_type,
            account_name=line.account_name,
            amount=delta,
            source_type=entry.source_type,
            source_id=entry.id,
            source_ref=entry.number,
            memo=line.memo or entry.memo,
            customer_id=line.customer_id,
            sales_pic_id=line.sales_pic_id,
            created_by=actor_id or entry.created_by,
        )
    entry.is_posted = True
    entry.posted_at = datetime.now(UTC)
    entry.posted_by = actor_id
    await db.flush()
    return entry


async def reverse_entry(db: AsyncSession, entry: JournalEntry, *,
                        actor_id: UUID | None = None,
                        reason: str | None = None,
                        on: date | None = None) -> JournalEntry:
    """Undo a posted journal by posting its mirror image.

    Not a delete and not an edit. The original stays exactly as it was
    posted, the reversal sits beside it, and the two net to nothing — which
    is the only way a correction can be explained to somebody reading the
    account six months later.
    """
    if not entry.is_posted:
        raise JournalError("A draft isn't posted — delete it instead.")
    if entry.reversed_by_id:
        raise JournalError(f"{entry.number} has already been reversed.")
    rows = [{
        "account_no": ln.account_no,
        # The mirror: what was debited is credited back.
        "debit": float(ln.credit or 0), "credit": float(ln.debit or 0),
        "memo": ln.memo, "customer_id": ln.customer_id,
        "sales_pic_id": ln.sales_pic_id,
    } for ln in entry.lines]
    mirror = await create_entry(
        db,
        entry_date=on or date.today(),
        rows=rows,
        memo=(reason or f"Reversal of {entry.number}"),
        source_type=entry.source_type,
        source_id=entry.source_id,
        source_ref=entry.number,
        created_by=actor_id,
        post=True,
        posted_by=actor_id,
    )
    mirror.reverses_id = entry.id
    entry.reversed_by_id = mirror.id
    await db.flush()
    return mirror


# The account a chart of accounts balances against when it is first written
# down. Every accounting package has one under some name; here it is the
# seeded "Equitas Saldo Awal".
OPENING_EQUITY = "300001"


async def post_opening_balances(
    db: AsyncSession, *, on: date, actor_id: UUID | None = None,
    equity_account: str = OPENING_EQUITY,
) -> JournalEntry | None:
    """Write down where the balances that were already here came from.

    A chart of accounts that arrives with balances on it — carried over from
    whatever kept the books before — has a real problem the moment anybody
    opens an account ledger: the balance says 5.382.000 and the ledger that
    is supposed to explain it shows nothing, or shows only the few entries
    posted since. Neither number is wrong; there is simply no record of the
    starting point.

    This posts that record: one entry, dated the day the books opened here,
    stating every account's balance as of then, with the difference carried
    to opening-balance equity so it balances like anything else. It applies
    nothing — the balances are already correct — and it stays out of the
    reporting journal so last year's trading is not counted as this month's.

    Returns None when there is nothing to write down.
    """
    from app.models.journal import CREDIT_NORMAL

    already = await db.scalar(
        select(JournalEntry).where(JournalEntry.source_type == "opening")
    )
    if already:
        raise JournalError(
            f"Opening balances were already recorded as {already.number} on "
            f"{already.entry_date}. They are written down once; a change "
            "after that is an ordinary journal entry."
        )
    # Opening balances are the starting point, so they go down before
    # anything else does. Written afterwards they would double-count: what
    # the journal has already explained would be stated a second time as if
    # it had always been there, and every account ledger would then close at
    # twice its account.
    started = await db.scalar(
        select(JournalEntry).where(JournalEntry.is_posted.is_(True),
                                   JournalEntry.source_type != "opening")
    )
    if started:
        raise JournalError(
            "The journal already has entries in it, so what is on the "
            f"accounts is partly explained by them ({started.number} and "
            "after). Opening balances are the starting point and have to be "
            "written down before the first entry; from here, an adjustment "
            "is an ordinary journal entry."
        )
    accounts = (await db.scalars(
        select(Account).where(Account.is_parent.is_(False))
        .order_by(Account.account_no.asc())
    )).all()

    rows: list[dict] = []
    net = 0.0
    for a in accounts:
        bal = round(float(a.balance or 0), 2)
        if not bal or a.account_no == equity_account:
            continue
        # The balance is stated in the direction the account is normally
        # read, so it goes in that column — and a negative one crosses over.
        credit_side = a.account_type in CREDIT_NORMAL
        if (bal > 0) == (not credit_side):
            rows.append({"account_no": a.account_no, "debit": abs(bal),
                         "memo": "Opening balance"})
            net += abs(bal)
        else:
            rows.append({"account_no": a.account_no, "credit": abs(bal),
                         "memo": "Opening balance"})
            net -= abs(bal)
    if not rows:
        return None
    # Whatever the accounts do not balance among themselves is equity —
    # which is the definition of equity, and why this account exists.
    if abs(net) > TOLERANCE:
        rows.append({
            "account_no": equity_account,
            "credit": net if net > 0 else 0,
            "debit": -net if net < 0 else 0,
            "memo": "Opening balance",
        })
    return await create_entry(
        db, entry_date=on, rows=rows,
        memo="Opening balances — carried in with the chart of accounts",
        source_type="opening", created_by=actor_id,
        post=True, posted_by=actor_id, back_fill=True,
    )
