-- And here, coalesce. A NULL amount arriving from upstream becomes 0 before any
-- test sees it, so the not_null test below cannot fail either. The data loss is
-- real and completely invisible to the suite.
select
    order_id,
    customer_id,
    status,
    coalesce(amount, 0) as amount
from {{ ref('stg_orders') }}
