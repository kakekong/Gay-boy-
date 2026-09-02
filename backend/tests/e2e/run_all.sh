#!/usr/bin/env bash
# Run every end-to-end driver against a scratch Postgres.
#
#   bash backend/tests/e2e/run_all.sh            # run all
#   bash backend/tests/e2e/run_all.sh --fresh    # recreate the DB first
#
# These drive the REAL ASGI app in-process (no mocks) with real role logins.
# Several use hardcoded document numbers (PO-CUST-A1, DP-001, INV-EF-001), so
# re-running them on a dirty DB produces "already exists" 409s that are test
# artifacts, NOT product bugs — use --fresh when in doubt.
set -uo pipefail
cd "$(dirname "$0")/../.."          # -> backend/

export DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test"
export APP_ENV=dev
export DEMO_SEED_PASSWORD=test-pass-123
export STORAGE_LOCAL_DIR=/tmp/storage_test
export JWT_SECRET=e2e-test-secret

pg_isready -h 127.0.0.1 -p 55432 -q || {
  echo "starting scratch postgres…"
  su -s /bin/bash nobody -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgdata_test \
    -o '-p 55432 -k /tmp -c listen_addresses=127.0.0.1' -l /tmp/pg_test.log start" >/dev/null 2>&1
  sleep 2
}

if [ "${1:-}" = "--fresh" ]; then
  # DROP DATABASE fails while anything is still connected — a stray dev server
  # on :8099 is enough. That used to be swallowed by >/dev/null, so --fresh
  # quietly kept the old database and the drivers ran on days-old leftovers
  # while claiming to be fresh. Kick the connections off, then insist it worked.
  su -s /bin/bash nobody -c "/usr/lib/postgresql/16/bin/psql -h /tmp -p 55432 -U postgres \
    -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity \
         WHERE datname = 'transmisi_test' AND pid <> pg_backend_pid()\"" >/dev/null 2>&1
  drop_out=$(su -s /bin/bash nobody -c "/usr/lib/postgresql/16/bin/psql -h /tmp -p 55432 -U postgres \
    -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS transmisi_test' \
    -c 'CREATE DATABASE transmisi_test'" 2>&1) || {
    echo "--fresh FAILED to recreate the database — refusing to run on stale data:"
    echo "$drop_out" | tail -3
    exit 1
  }
  rm -rf /tmp/storage_test/* 2>/dev/null
  python -m app.scripts.seed >/dev/null 2>&1
  # The seed now creates all eight demo logins, purchasing and finance
  # included. This stays as a safety net for a database seeded by an older
  # build — and it makes the employee record too, because an internal login
  # without one is exactly what the drivers check is refused.
  python - <<'PY' >/dev/null 2>&1
import asyncio
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.employee import Employee
from app.models.user import User
async def m():
    async with SessionLocal() as db:
        for i, (e, n, r) in enumerate([
                ("purchasing@demo.local", "Purchasing Demo", "purchasing"),
                ("finance@demo.local", "Finance Demo", "finance")], start=90):
            if not await db.scalar(select(User).where(User.email == e)):
                emp = Employee(employee_no=f"EMP-DEMO-{i:03d}", full_name=n,
                               intended_role=r, is_active=True)
                db.add(emp)
                await db.flush()
                db.add(User(email=e, full_name=n, role=r, employee_id=emp.id,
                            password_hash=hash_password("test-pass-123"), is_active=True))
        await db.commit()
asyncio.run(m())
PY
  echo "fresh DB seeded"
fi

fail=0
for f in tests/e2e/*.py; do
  name=$(basename "$f" .py)
  printf '%-24s ' "$name"
  out=$(python "$f" 2>&1)
  line=$(echo "$out" | grep -E "PROBLEMS:|passed, [0-9]+ failed|CONFIRMED HOLES" | tail -1)
  echo "${line:-NO RESULT (see below)}"
  echo "$line" | grep -qE "PROBLEMS: 0|0 failed|CONFIRMED HOLES: 0" || { fail=1; echo "$out" | tail -5; }
done

echo
echo "=== pytest unit suites ==="
PYTHONPATH=. python -m pytest tests/test_permissions.py tests/test_discount_rules.py \
  tests/test_financials.py tests/test_depreciation.py -q 2>&1 | tail -2
echo "=== DP flow ==="
dp=$(python tests/e2e_dp_flow.py 2>&1)
echo "$dp" | grep RESULT || echo "DP flow: NO RESULT"
# Name the failing checks. Printing only the tally left us guessing which one
# broke, which is exactly when you most want the name.
echo "$dp" | grep -E "^  FAIL" || true
echo "$dp" | grep RESULT | grep -qE "RESULT: [0-9]+ passed, 0 failed" || fail=1

exit $fail
