-- London Seed Radar schema.
-- radar.db is the local working source of truth (gitignored).
-- The public dataset is exported to docs/data/ by python -m radar.publish.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    company_number TEXT UNIQUE,
    domain TEXT UNIQUE,
    website TEXT,
    website_status TEXT,             -- live | unknown (only 'live' is ever
                                     -- written, on a reality-gate pass)
    location_text TEXT,              -- registered office or press location mention
    incorporated_on TEXT,
    one_liner TEXT,
    one_liner_source TEXT,
    headcount_estimate TEXT,         -- bucket: 1-10 | 11-25 | 26-50 | 51-100 | unknown
    headcount_source TEXT,
    ats_provider TEXT,               -- greenhouse | ashby | lever
    ats_token TEXT,
    ats_status TEXT,                 -- verified | unverifiable | none
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS funding_events (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    stage TEXT,                      -- pre-seed | seed | series-a | series-b.. | NULL=unknown
    amount_gbp INTEGER,              -- best effort; SH01 rarely states it, press preferred
    amount_source TEXT,
    event_date TEXT NOT NULL,        -- ISO date of filing or press publication
    filing_id TEXT,                  -- Companies House transaction id, if filed
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered','sieved','enriched','featured','published','dropped')),
    drop_reason TEXT,
    gates_json TEXT,                 -- per-gate outcomes recorded by sieve
    source_mode TEXT NOT NULL DEFAULT 'live'
        CHECK (source_mode IN ('live','fixture')),
    issue_date TEXT,                 -- set when featured in an issue
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (company_id, event_date)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    funding_event_id INTEGER NOT NULL REFERENCES funding_events(id),
    kind TEXT NOT NULL CHECK (kind IN ('filing','press')),
    source_name TEXT,                -- e.g. Companies House, UKTN
    url TEXT,
    title TEXT,
    snippet TEXT,
    published_date TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (funding_event_id, kind, url)
);

-- Founders: names and public roles only. No contact data, by design.
-- There are deliberately no email or phone columns; do not add them.
CREATE TABLE IF NOT EXISTS founders (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    role TEXT,
    background TEXT,                 -- one public-record line, from company site or press
    source_url TEXT,
    UNIQUE (company_id, name)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL,
    location TEXT,
    url TEXT,
    ats_provider TEXT,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT,                  -- stamped by every ATS fetch; the site
                                     -- and dataset export only postings seen
                                     -- by a company's latest fetch, so
                                     -- closed roles age out honestly
    UNIQUE (company_id, url)
);

CREATE TABLE IF NOT EXISTS human_todos (
    id INTEGER PRIMARY KEY,
    task TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('setup','issue','growth')),
    due_hint TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done')),
    issue_date TEXT,                 -- issue tasks are tied to an issue
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    done_at TEXT
);

-- Logged manually by the human, never estimated by code.
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    subscribers INTEGER,
    open_rate REAL,
    replies_from_founders INTEGER,
    revenue_gbp REAL,
    notes TEXT
);
-- One row per date, enforced as an index so existing databases pick the
-- constraint up on the next init_db. Correcting a logged number is an
-- explicit act: python -m radar.metrics log --amend.
CREATE UNIQUE INDEX IF NOT EXISTS idx_metrics_date ON metrics(date);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    issue_date TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    published_at TEXT
);
