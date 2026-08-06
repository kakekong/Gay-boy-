# Sample files for testing the importers

Four small files, each a real slice of the company's own Accurate exports.
They are cut to work **in order**, so running all four is a complete rehearsal
of the real thing:

| # | File | What it is | What it should do |
|---|---|---|---|
| 1 | `SAMPLE-1-pelanggan.xlsx` | 11 rows of *Daftar Pelanggan* | 10 import, 1 flagged as a duplicate of another row |
| 2 | `SAMPLE-2-barang.xlsx` | 15 rows of *Barang & Jasa* | 15 import, with a note that the file carries no prices |
| 3 | `SAMPLE-3-akun.xlsx` | 22 rows of *Daftar Akun* | 15 import, 7 already in the app, 1 name differs |
| 4 | `SAMPLE-4-penawaran.xlsx` | 8 sheets of *Rincian Penawaran Penjualan* | 8 import, 39 line items, all matched to customers from file 1 |

The order matters: a quotation needs a customer to belong to, and the eight
quotations in file 4 name customers that file 1 contains. Run 4 first and all
eight are correctly skipped as "no customer" — which is itself worth seeing
once.

File 3 is deliberately *not* the first 22 rows of the real export. The app's
chart of accounts was seeded from these same books, so the first 22 rows are
all accounts it already has and the import reports "already here" 22 times.
This slice is the 15 accounts the seed does **not** have plus 7 that it does,
so it demonstrates both halves — including `1101-01`, which the two systems
name differently and which the import reports without changing.

## Undoing a test run

*Clear test data* → **Pick specific records**. Search by number, tick, and
delete. All four kinds are covered: customers, quotations, parts and accounts.

Deleting a customer or a quotation takes everything created from it, and the
preview lists every one of those documents before anything happens. Parts and
accounts have nothing hanging off them, so they go on their own.
