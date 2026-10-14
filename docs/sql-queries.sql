-- ERIMS key SQL queries (Week 1, Day 4)
-- Run in pgAdmin's Query Tool or in psql:  psql -U erims_user -d erims
-- These are the same questions the app will answer in Week 2 (via the Django ORM).

-- 1. Current usable stock per supply per location (expired batches excluded)
SELECT l.code      AS location,
       s.sku,
       s.name      AS supply,
       SUM(b.quantity) AS usable_qty,
       s.reorder_level
FROM inventory_stockbatch b
JOIN inventory_supply   s ON s.id = b.supply_id
JOIN inventory_location l ON l.id = b.location_id
WHERE b.quantity > 0
  AND (b.expiry_date IS NULL OR b.expiry_date >= CURRENT_DATE)
GROUP BY l.code, s.sku, s.name, s.reorder_level
ORDER BY l.code, s.name;

-- 2. LOW-STOCK ALERT: supplies below their reorder level at each location
--    (includes supplies with zero stock at a location)
SELECT l.code AS location,
       s.name AS supply,
       COALESCE(SUM(b.quantity) FILTER (
           WHERE b.expiry_date IS NULL OR b.expiry_date >= CURRENT_DATE), 0) AS usable_qty,
       s.reorder_level
FROM inventory_location l
CROSS JOIN inventory_supply s
LEFT JOIN inventory_stockbatch b
       ON b.location_id = l.id AND b.supply_id = s.id AND b.quantity > 0
WHERE l.is_active AND s.is_active
GROUP BY l.code, s.name, s.reorder_level
HAVING COALESCE(SUM(b.quantity) FILTER (
           WHERE b.expiry_date IS NULL OR b.expiry_date >= CURRENT_DATE), 0) < s.reorder_level
ORDER BY l.code, s.name;

-- 3. EXPIRY ALERT: batches expired or expiring in the next 30 days
SELECT l.code AS location,
       s.name AS supply,
       b.batch_number,
       b.quantity,
       b.expiry_date,
       b.expiry_date - CURRENT_DATE AS days_left,
       CASE WHEN b.expiry_date < CURRENT_DATE THEN 'EXPIRED' ELSE 'EXPIRING SOON' END AS status
FROM inventory_stockbatch b
JOIN inventory_supply   s ON s.id = b.supply_id
JOIN inventory_location l ON l.id = b.location_id
WHERE b.quantity > 0
  AND b.expiry_date <= CURRENT_DATE + 30
ORDER BY b.expiry_date;

-- 4. READINESS CHECK for one emergency: required vs available at its response location
SELECT e.name AS emergency,
       s.name AS supply,
       r.quantity_required,
       COALESCE(SUM(b.quantity), 0) AS available_at_location,
       GREATEST(r.quantity_required - COALESCE(SUM(b.quantity), 0), 0) AS shortage,
       CASE WHEN COALESCE(SUM(b.quantity), 0) >= r.quantity_required THEN 'READY' ELSE 'SHORTAGE' END AS status
FROM emergencies_emergencyevent e
JOIN emergencies_eventrequirement r ON r.event_id = e.id
JOIN inventory_supply s             ON s.id = r.supply_id
LEFT JOIN inventory_stockbatch b
       ON b.supply_id = r.supply_id
      AND b.location_id = e.response_location_id
      AND b.quantity > 0
      AND (b.expiry_date IS NULL OR b.expiry_date >= CURRENT_DATE)
WHERE e.status = 'ACTIVE'
GROUP BY e.name, s.name, r.quantity_required, r.priority
ORDER BY r.priority, s.name;

-- 5. TRANSFER CANDIDATES: other locations with surplus above their reorder level
SELECT s.name AS supply,
       l.code AS source_location,
       SUM(b.quantity) AS usable_qty,
       s.reorder_level,
       SUM(b.quantity) - s.reorder_level AS spare_qty
FROM inventory_stockbatch b
JOIN inventory_supply   s ON s.id = b.supply_id
JOIN inventory_location l ON l.id = b.location_id
WHERE b.quantity > 0
  AND (b.expiry_date IS NULL OR b.expiry_date >= CURRENT_DATE)
  AND l.code <> 'CXB-RC'                    -- exclude the location that needs the stock
GROUP BY s.name, l.code, s.reorder_level
HAVING SUM(b.quantity) > s.reorder_level
ORDER BY s.name, spare_qty DESC;

-- 6. AUDIT TRAIL: latest 20 stock movements
SELECT t.created_at,
       t.transaction_type,
       s.name  AS supply,
       t.quantity,
       fl.code AS from_location,
       tl.code AS to_location,
       u.username AS performed_by,
       t.reason
FROM inventory_stocktransaction t
JOIN inventory_supply s        ON s.id = t.supply_id
LEFT JOIN inventory_location fl ON fl.id = t.from_location_id
LEFT JOIN inventory_location tl ON tl.id = t.to_location_id
LEFT JOIN auth_user u           ON u.id = t.performed_by_id
ORDER BY t.created_at DESC
LIMIT 20;
