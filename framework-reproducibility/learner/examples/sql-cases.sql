-- Draft visible inputs. Canonical output and statement isolation remain pending.
SELECT a.id, b.name
FROM customer a LEFT JOIN profile b
  ON a.id = b.customer_id AND a.region = b.region AND b.enabled = 1;

SELECT a.id FROM event a JOIN validity b
  ON a.event_time >= b.start_time AND a.event_time < b.end_time;

SELECT a.id FROM customer a JOIN profile b USING (id);

SELECT a.id FROM customer a CROSS JOIN region b;

SELECT a.id FROM customer a JOIN profile b ON id = b.id;

WITH chosen AS (SELECT id FROM customer)
SELECT c.id FROM chosen c JOIN profile p ON c.id = p.customer_id;

SELECT a.id FROM customer a JOIN profile b
  ON CONCAT(a.region, a.id) = b.external_key;

INSERT INTO target_profile (customer_id, label)
SELECT c.id, p.name FROM customer c JOIN profile p ON c.id = p.customer_id;
