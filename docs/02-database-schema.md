# 02 — Database Schema (PostgreSQL)

> All tables include `id UUID PK`, `created_at`, `updated_at`, `created_by`, `updated_by`, `is_deleted`, `deleted_at`.
> Engine: PostgreSQL 15 with `pgvector` extension for embeddings.

## 2.1 ERD overview

```
users ─┬─< customers >─┬─< activities
       │                ├─< reminders
       │                ├─< quotations >─┬─< quotation_items
       │                                  └─< approval_requests
       └─< sales_targets

customers ─< projects >─┬─< work_orders
                        ├─< purchase_requests >─< rfqs >─< supplier_pos >─< goods_receipts >─< qc_reports
                        ├─< delivery_orders >─< invoices >─< payments
                        ├─< drawings (approval workflow)
                        └─< project_costs   (profit intelligence)

ai_*            ─ lead_scores, deal_risks, embeddings, kb_documents, document_parses
audit_log       ─ universal change log
approval_requests ─ generic approval engine
```

## 2.2 Core tables

### `users`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| email | citext | unique |
| password_hash | text | argon2 |
| full_name | text | |
| role | enum(`sales`,`admin`,`manager`,`director`) | RBAC |
| phone | text | E.164 |
| whatsapp_id | text | for WA integration |
| is_active | bool | |

### `customers`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| company_name | text | |
| industry | enum(`mining`,`pltu`,`fertilizer`,`sugar`,`cement`,`pulp_paper`,`food`,`other`) | |
| pic_name | text | |
| pic_position | text | |
| phone | text | |
| whatsapp | text | |
| email | citext | |
| company_address | text | |
| delivery_address | text | |
| sales_pic_id | uuid → users.id | RBAC scope |
| stage | enum(`lead`,`presentation`,`engineering`,`quotation`,`negotiation`,`po`,`drawing`,`purchasing`,`delivery`,`invoicing`,`payment`,`closed_won`,`closed_lost`) | pipeline |
| payment_terms | jsonb | e.g. `{type:"termin", schedule:[...]}` |
| lifetime_value | numeric | rolled up |
| lost_reason | text | nullable |
| meta | jsonb | extension |

### `activities`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| customer_id | uuid → customers.id | |
| user_id | uuid → users.id | who logged |
| type | enum(`call`,`presentation`,`technical_meeting`,`purchase_request`,`quotation_sent`,`negotiation`,`follow_up`,`whatsapp_in`,`whatsapp_out`,`email`,`note`) | |
| direction | enum(`inbound`,`outbound`,`internal`) | |
| occurred_at | timestamptz | |
| notes | text | |
| meta | jsonb | WA message id, attachments |

### `reminders`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| customer_id | uuid | nullable |
| project_id | uuid | nullable |
| invoice_id | uuid | nullable |
| user_id | uuid → users.id | assignee |
| kind | enum(`follow_up`,`after_sales`,`delivery`,`payment_due`) | |
| due_at | timestamptz | |
| ai_optimal_at | timestamptz | Smart Reminder Engine |
| status | enum(`pending`,`sent`,`done`,`snoozed`) | |
| channel | enum(`whatsapp`,`dashboard`,`email`) | |
| message | text | |

## 2.3 Quotation

### `quotations`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| number | text | unique, e.g. `QT-2026-0001` |
| customer_id | uuid | |
| project_id | uuid | nullable |
| version | int | multi-version |
| parent_id | uuid → quotations.id | previous version |
| variant | enum(`short`,`detailed`) | |
| sales_pic_id | uuid → users.id | |
| status | enum(`draft`,`pending_approval`,`approved`,`rejected`,`sent`,`won`,`lost`) | |
| currency | text | IDR/USD |
| subtotal | numeric | |
| discount_pct | numeric | |
| discount_amount | numeric | |
| tax_pct | numeric | |
| total | numeric | |
| valid_until | date | |
| notes | text | |
| pdf_url | text | |

### `quotation_items`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| quotation_id | uuid | |
| line_no | int | |
| source | enum(`product`,`custom`) | std product vs custom engineering |
| product_id | uuid | nullable, links to `products` master |
| description | text | |
| spec | jsonb | engineering spec (custom items) |
| qty | numeric | |
| uom | text | |
| unit_price | numeric | |
| cost_estimate | numeric | for profit engine |
| line_total | numeric | |

### `products` (master, for "standard" line items)
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| code | text | unique |
| name | text | |
| category | text | |
| uom | text | |
| list_price | numeric | |
| std_cost | numeric | |
| spec | jsonb | |

## 2.4 Approval engine

### `approval_requests`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| target_type | text | e.g. `quotation`, `discount`, `data_change` |
| target_id | uuid | |
| requested_by | uuid → users.id | |
| required_role | enum(`manager`,`director`) | from rule engine |
| reason | text | |
| status | enum(`pending`,`approved`,`rejected`) | |
| decided_by | uuid | nullable |
| decided_at | timestamptz | nullable |
| decision_notes | text | |
| payload | jsonb | snapshot of changes |

Rule examples (see `core/approval_rules.py`):
- discount ≤ 5% → auto approved
- 5% < discount ≤ 15% → manager
- discount > 15% → director
- any data change made by `admin` role → manager

## 2.5 Project / Operation

### `projects`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| code | text | `PRJ-2026-0001` |
| customer_id | uuid | |
| quotation_id | uuid | won quotation that became a project |
| po_number | text | customer PO number |
| po_date | date | |
| po_value | numeric | |
| start_date | date | |
| target_delivery | date | |
| actual_delivery | date | nullable |
| status | enum(`new`,`drawing`,`drawing_approved`,`purchasing`,`production`,`qc`,`packaging`,`delivered`,`invoiced`,`paid`,`closed`) | |
| margin_estimate | numeric | profit engine |
| margin_actual | numeric | nullable |

### `work_orders`
linked to project; tracks production stages: receiving, warehousing, QC, packaging, delivery.

### `drawings`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| project_id | uuid | |
| revision | int | |
| file_url | text | |
| status | enum(`draft`,`submitted`,`approved`,`revision_requested`) | |
| customer_decision_at | timestamptz | |

### `delivery_orders`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| project_id | uuid | |
| number | text | `DO-2026-0001` |
| split_index | int | for split delivery per PO |
| courier | text | |
| tracking_no | text | resi |
| delivered_at | timestamptz | |
| status | enum(`pending`,`in_transit`,`delivered`,`returned`) | |

## 2.6 Purchasing

### `purchase_requests` → `rfqs` → `supplier_pos` → `goods_receipts` → `qc_reports`

```
purchase_requests (PR)
  ├─ pr_items
  └─< rfqs (request for quotation)
        ├─ rfq_lines
        └─< supplier_pos
              ├─ po_lines
              ├─< goods_receipts (GR)
              │     └─ gr_lines
              └─< qc_reports
```

### `suppliers`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| name | text | |
| category | text | |
| rating | numeric | rolled up: lead time, QC pass rate |
| lead_time_days_avg | numeric | |
| qc_fail_rate | numeric | |
| price_volatility | numeric | |
| meta | jsonb | |

## 2.7 Finance

### `invoices`
| column | type | notes |
|---|---|---|
| id | uuid | PK |
| number | text | `INV-2026-0001` |
| project_id | uuid | |
| customer_id | uuid | |
| type | enum(`dp`,`settlement`,`termin`,`tempo`,`single`) | payment type |
| termin_index | int | for progress payment |
| issue_date | date | |
| due_date | date | |
| amount | numeric | |
| tax_amount | numeric | |
| total | numeric | |
| status | enum(`draft`,`issued`,`partial`,`paid`,`overdue`,`void`) | |
| pdf_url | text | |

### `payments`
| invoice_id, paid_at, amount, method, reference, notes |

### `project_costs` — for Profit Intelligence
| project_id, category(`material`,`purchasing`,`logistics`,`labor`,`discount`,`other`), amount, occurred_at, source_ref |

## 2.8 AI tables

### `lead_scores`
| customer_id, score (0–100), drivers jsonb, recommended_action, model_version, computed_at |

### `deal_risks`
| project_id (or quotation_id), risk_level (`low`,`medium`,`high`), reasons jsonb, recommended_action, computed_at |

### `embeddings`
| id, owner_type, owner_id, content text, embedding vector(1536), created_at |
- index: `ivfflat (embedding vector_cosine_ops)`
- used by Knowledge Base AI

### `kb_documents`
| id, title, source, tags text[], body text, embedding_id |

### `document_parses`
| id, source(`po`,`whatsapp`,`email`,`pdf`,`image`), raw_url, extracted jsonb, confidence, status |

### `loss_analyses`
| project_id (lost), competitor, price_diff_pct, response_lag_hours, spec_mismatch text, learnings jsonb |

## 2.9 Audit & misc

### `audit_log`
| id, actor_id, action, entity, entity_id, before jsonb, after jsonb, ip, user_agent, occurred_at |

### `sales_targets`
| user_id, period (month/quarter), target_amount, achieved_amount |

## 2.10 Indexes (selection)

```sql
CREATE INDEX ix_customers_sales_pic ON customers(sales_pic_id) WHERE is_deleted = false;
CREATE INDEX ix_customers_stage ON customers(stage);
CREATE INDEX ix_quotations_status ON quotations(status);
CREATE INDEX ix_invoices_due ON invoices(due_date) WHERE status IN ('issued','partial','overdue');
CREATE INDEX ix_activities_customer_time ON activities(customer_id, occurred_at DESC);
CREATE INDEX ix_embeddings_vec ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);
```
