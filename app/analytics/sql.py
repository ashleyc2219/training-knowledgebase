"""DDL 與查詢常數。

9 張表逐欄對齊 `docs/spec/erm.dbml`（型別 int→INTEGER、string→TEXT、bool→INTEGER(0/1)、float→REAL）。
查詢一律用 `:name` 具名參數（sqlite3 與 hotdata 都能吃）。
"""

from __future__ import annotations

DDL: dict[str, str] = {
    "Ticket": """
CREATE TABLE IF NOT EXISTS Ticket (
    id INTEGER PRIMARY KEY,
    content TEXT,
    resolution_steps TEXT,
    category TEXT,
    customer_ref TEXT,
    feature_id INTEGER,
    user_problem_id INTEGER,
    status TEXT,
    deflected_tutorial_id INTEGER,
    deflected_tutorial_version TEXT,
    reopened_from_ticket_id INTEGER,
    created_at TEXT
)
""",
    "UserProblem": """
CREATE TABLE IF NOT EXISTS UserProblem (
    id INTEGER PRIMARY KEY,
    topic TEXT,
    feature_id INTEGER
)
""",
    "Feature": """
CREATE TABLE IF NOT EXISTS Feature (
    id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT
)
""",
    "Tutorial": """
CREATE TABLE IF NOT EXISTS Tutorial (
    tutorial_id INTEGER PRIMARY KEY,
    feature_id INTEGER,
    user_problem_id INTEGER,
    path TEXT,
    status TEXT,
    current_version TEXT,
    is_possibly_outdated INTEGER DEFAULT 0,
    is_obsolete INTEGER DEFAULT 0,
    last_action TEXT
)
""",
    "TutorialVersion": """
CREATE TABLE IF NOT EXISTS TutorialVersion (
    tutorial_id INTEGER,
    tutorial_version TEXT,
    title TEXT,
    problem TEXT,
    prerequisites TEXT,
    steps TEXT,
    expected_outcome TEXT,
    reason TEXT,
    supersedes_version TEXT,
    created_at TEXT,
    PRIMARY KEY (tutorial_id, tutorial_version)
)
""",
    "Feedback": """
CREATE TABLE IF NOT EXISTS Feedback (
    id INTEGER PRIMARY KEY,
    tutorial_id INTEGER,
    tutorial_version TEXT,
    rating INTEGER,
    feedback_category TEXT,
    comment TEXT,
    submitter_id TEXT,
    timestamp TEXT
)
""",
    "Release": """
CREATE TABLE IF NOT EXISTS Release (
    id INTEGER PRIMARY KEY,
    content TEXT,
    created_at TEXT,
    processed_at TEXT
)
""",
    "ReleaseFeatureChange": """
CREATE TABLE IF NOT EXISTS ReleaseFeatureChange (
    id INTEGER PRIMARY KEY,
    release_id INTEGER,
    feature_id INTEGER,
    change_type TEXT,
    from_name TEXT,
    to_name TEXT
)
""",
    "Workflow": """
CREATE TABLE IF NOT EXISTS Workflow (
    id INTEGER PRIMARY KEY,
    user_problem_id INTEGER,
    steps TEXT,
    captured_at TEXT,
    replay_count INTEGER DEFAULT 0
)
""",
}

TABLES: list[str] = list(DDL.keys())

# --- 輪詢（features/輪詢新票單.feature、輪詢ReleaseNote.feature） ---

POLL_OPEN_TICKETS = """
SELECT * FROM Ticket
WHERE created_at > :last_checked AND status = 'open'
ORDER BY created_at
"""

# 相同 content + created_at 已存在時不新增列（輪詢ReleaseNote.feature）
POLL_CHANGELOG = """
SELECT :content AS content, :created_at AS created_at
WHERE NOT EXISTS (
    SELECT 1 FROM Release
    WHERE content = :content AND created_at = :created_at
)
"""

UNPROCESSED_RELEASES = """
SELECT * FROM Release
WHERE processed_at IS NULL OR processed_at = ''
ORDER BY created_at
"""

# --- 學習指標（features/展示學習指標.feature、showme.md §12） ---

DEFLECTION_RATE = """
SELECT
    SUM(CASE WHEN status = 'deflected' THEN 1 ELSE 0 END) AS deflected,
    SUM(CASE WHEN status IN ('deflected', 'escalated') THEN 1 ELSE 0 END) AS denominator
FROM Ticket
"""

REPLAY_RATE = """
SELECT
    (SELECT COALESCE(SUM(replay_count), 0) FROM Workflow) AS replays,
    (SELECT COUNT(*) FROM Ticket WHERE status = 'deflected') AS deflected
"""

COVERAGE = """
SELECT
    (SELECT COUNT(DISTINCT user_problem_id) FROM Tutorial WHERE status = 'published') AS covered,
    (SELECT COUNT(*) FROM UserProblem) AS total
"""

# --- Feedback Review（features/定期優化Tutorial.feature；只算 current_version） ---

AVG_RATING_CURRENT_VERSION = """
SELECT AVG(f.rating) AS avg_rating, COUNT(*) AS feedback_count
FROM Feedback f
JOIN Tutorial t
  ON t.tutorial_id = f.tutorial_id
 AND t.current_version = f.tutorial_version
WHERE f.tutorial_id = :tutorial_id
"""

SAME_CATEGORY_MAX = """
SELECT f.feedback_category AS feedback_category, COUNT(*) AS category_count
FROM Feedback f
JOIN Tutorial t
  ON t.tutorial_id = f.tutorial_id
 AND t.current_version = f.tutorial_version
WHERE f.tutorial_id = :tutorial_id AND f.feedback_category <> ''
GROUP BY f.feedback_category
ORDER BY category_count DESC
"""

# --- 分析 Ticket（features/分析SupportTickets.feature；只納入 escalated / resolved） ---

RECURRING_TOPICS = """
SELECT t.user_problem_id AS user_problem_id,
       up.topic AS topic,
       COUNT(*) AS ticket_count
FROM Ticket t
JOIN UserProblem up ON up.id = t.user_problem_id
WHERE t.status IN ('escalated', 'resolved')
  AND t.user_problem_id IS NOT NULL
GROUP BY t.user_problem_id, up.topic
HAVING COUNT(*) >= 3
"""
