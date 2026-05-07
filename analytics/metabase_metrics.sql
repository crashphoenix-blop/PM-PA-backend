-- Surprise analytics metrics for Metabase (PostgreSQL).
-- Table source: analytics_events

-- 1) Cumulative unique users (all who entered app start screen)
SELECT COUNT(DISTINCT COALESCE(user_id::text, anonymous_id)) AS cumulative_unique_users
FROM analytics_events
WHERE event_name = 'site_open';

-- 2) Cumulative unique active users (completed onboarding)
SELECT COUNT(DISTINCT COALESCE(user_id::text, anonymous_id)) AS cumulative_unique_active_users
FROM analytics_events
WHERE event_name = 'onboarding_completed';

-- 3) DAU (daily active users)
SELECT
  DATE_TRUNC('day', event_time) AS day,
  COUNT(DISTINCT COALESCE(user_id::text, anonymous_id)) AS dau
FROM analytics_events
WHERE event_name = 'site_open'
GROUP BY 1
ORDER BY 1 DESC;

-- 4) MAU (monthly active users)
SELECT
  DATE_TRUNC('month', event_time) AS month,
  COUNT(DISTINCT COALESCE(user_id::text, anonymous_id)) AS mau
FROM analytics_events
WHERE event_name = 'site_open'
GROUP BY 1
ORDER BY 1 DESC;

-- 5) Average user time on site (seconds)
WITH session_durations AS (
  SELECT
    session_id,
    MAX(duration_seconds) AS duration_seconds
  FROM analytics_events
  WHERE event_name = 'session_end'
    AND session_id IS NOT NULL
  GROUP BY session_id
)
SELECT AVG(duration_seconds) AS avg_time_on_site_seconds
FROM session_durations;

-- 6) Total clicks on "перейти к покупке"
SELECT COUNT(*) AS total_purchase_clicks
FROM analytics_events
WHERE event_name = 'purchase_click';

-- 7) Clicks on "перейти к покупке" per gift
SELECT
  gift_id,
  COUNT(*) AS purchase_clicks
FROM analytics_events
WHERE event_name = 'purchase_click'
  AND gift_id IS NOT NULL
GROUP BY gift_id
ORDER BY purchase_clicks DESC;

-- 8) Total clicks on "добавить в избранное"
SELECT COUNT(*) AS total_favorite_clicks
FROM analytics_events
WHERE event_name = 'favorite_click';

-- 9) Clicks on "добавить в избранное" per gift
SELECT
  gift_id,
  COUNT(*) AS favorite_clicks
FROM analytics_events
WHERE event_name = 'favorite_click'
  AND gift_id IS NOT NULL
GROUP BY gift_id
ORDER BY favorite_clicks DESC;

-- 10) Onboarding completion rate (%)
WITH entrants AS (
  SELECT COUNT(DISTINCT COALESCE(user_id::text, anonymous_id)) AS users_count
  FROM analytics_events
  WHERE event_name = 'site_open'
),
completed AS (
  SELECT COUNT(DISTINCT COALESCE(user_id::text, anonymous_id)) AS users_count
  FROM analytics_events
  WHERE event_name = 'onboarding_completed'
)
SELECT
  CASE
    WHEN entrants.users_count = 0 THEN 0
    ELSE ROUND((completed.users_count::numeric / entrants.users_count::numeric) * 100, 2)
  END AS onboarding_completion_rate_percent
FROM entrants, completed;
