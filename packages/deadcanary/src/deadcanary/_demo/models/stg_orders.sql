-- Note the WHERE clause. It is the whole point of the demo.
--
-- Any row arriving with an unexpected status is silently dropped here, so the
-- accepted_values test on this model can never fail no matter what upstream
-- sends. It has been green since the day it was written and it is protecting
-- nothing. That is a dead canary, and it is a real shape, not a contrived one --
-- filtering to known-good values then testing for known-good values is one of
-- the most common patterns in a warehouse.
select
    id as order_id,
    customer_id,
    status,
    amount
from {{ ref('raw_orders') }}
where status in ('placed', 'shipped', 'completed')
