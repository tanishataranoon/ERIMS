# ERIMS — Entity Relationship Diagram (MVP)

GitHub renders this diagram automatically. To export it as an image for your
report, paste the code block into https://mermaid.live and download PNG/SVG.

```mermaid
erDiagram
    USER ||--o{ STOCK_TRANSACTION : "performs"
    USER }o--o{ GROUP : "has role"
    LOCATION ||--o{ STOCK_BATCH : "stores"
    CATEGORY ||--o{ SUPPLY : "groups"
    SUPPLY ||--o{ STOCK_BATCH : "stocked as"
    SUPPLY ||--o{ STOCK_TRANSACTION : "moved in"
    STOCK_BATCH ||--o{ STOCK_TRANSACTION : "affected by"
    LOCATION ||--o{ STOCK_TRANSACTION : "from / to"
    LOCATION ||--o{ EMERGENCY_EVENT : "response hub for"
    EMERGENCY_EVENT ||--o{ EVENT_REQUIREMENT : "needs"
    SUPPLY ||--o{ EVENT_REQUIREMENT : "required as"
    EMERGENCY_EVENT ||--o{ STOCK_TRANSACTION : "linked to"

    LOCATION {
        bigint id PK
        varchar code UK
        varchar name UK
        varchar location_type "WAREHOUSE | DEPOT | RELIEF_CENTER"
        varchar district
        boolean is_active
    }
    CATEGORY {
        bigint id PK
        varchar name UK
    }
    SUPPLY {
        bigint id PK
        varchar sku UK
        varchar name
        bigint category_id FK
        varchar unit "PIECE | KG | LITRE | PACK | BOX"
        int reorder_level
        boolean tracks_expiry
    }
    STOCK_BATCH {
        bigint id PK
        bigint supply_id FK
        bigint location_id FK
        varchar batch_number
        int quantity "CHECK >= 0"
        date expiry_date "nullable"
        date received_date
    }
    STOCK_TRANSACTION {
        bigint id PK
        varchar transaction_type "RECEIVED | DISPATCHED | TRANSFERRED | ADJUSTED | DAMAGED | EXPIRED"
        bigint supply_id FK
        bigint batch_id FK
        int quantity "CHECK > 0"
        bigint from_location_id FK "nullable"
        bigint to_location_id FK "nullable"
        bigint emergency_event_id FK "nullable"
        bigint performed_by_id FK
        varchar reference
        text reason
        timestamptz created_at
    }
    EMERGENCY_EVENT {
        bigint id PK
        varchar name
        varchar event_type
        varchar severity
        varchar status "PLANNED | ACTIVE | CLOSED"
        bigint response_location_id FK
        date start_date
    }
    EVENT_REQUIREMENT {
        bigint id PK
        bigint event_id FK
        bigint supply_id FK
        int quantity_required
        smallint priority
    }
    USER {
        int id PK
        varchar username UK
    }
    GROUP {
        int id PK
        varchar name "Admin | Inventory Manager | Viewer"
    }
```

## Design notes (useful for your report / viva)

1. **Stock is stored per batch**, not as one number per supply. A batch is a
   quantity of one supply at one location with one expiry date. This makes
   expiry alerts and First-Expiry-First-Out (FEFO) dispatch possible.
2. **Quantities are never edited directly.** All changes go through
   `inventory/services.py`, which writes a `STOCK_TRANSACTION` row every time.
   That table is the audit trail: who moved what, from where, to where, when and why.
3. **Database constraints protect the data even if code has a bug:**
   quantity can never be negative, transaction quantity must be positive,
   every transaction must have at least one location, and a supply can only
   appear once per emergency's requirement list.
4. **Concurrency:** stock operations lock the batch rows they change
   (`SELECT … FOR UPDATE`) inside a database transaction, so two users can't
   dispatch the same stock at the same time.
5. **`PROTECT` foreign keys:** a supply or location that has stock or history
   cannot be deleted — deactivate it with `is_active` instead.
