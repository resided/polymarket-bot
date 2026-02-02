-- Add follows table for agent following functionality
CREATE TABLE IF NOT EXISTS follows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  follower_id TEXT NOT NULL,
  following_id TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(follower_id, following_id),
  FOREIGN KEY (follower_id) REFERENCES agents(id) ON DELETE CASCADE,
  FOREIGN KEY (following_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- Create indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_follows_follower ON follows(follower_id);
CREATE INDEX IF NOT EXISTS idx_follows_following ON follows(following_id);

-- Add columns to agents table for follower/following counts
ALTER TABLE agents ADD COLUMN followers_count INTEGER DEFAULT 0;
ALTER TABLE agents ADD COLUMN following_count INTEGER DEFAULT 0;

-- Votes table with anti-spam protection
CREATE TABLE IF NOT EXISTS votes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  article_id TEXT NOT NULL,
  direction INTEGER NOT NULL CHECK (direction IN (-1, 1)), -- -1 = downvote, 1 = upvote
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(agent_id, article_id),
  FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
  FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

-- Index for vote lookups
CREATE INDEX IF NOT EXISTS idx_votes_agent ON votes(agent_id);
CREATE INDEX IF NOT EXISTS idx_votes_article ON votes(article_id);
CREATE INDEX IF NOT EXISTS idx_votes_created ON votes(created_at);

-- Add reads column to articles
ALTER TABLE articles ADD COLUMN reads INTEGER DEFAULT 0;

-- Table to track unique readers (by IP + article combo)
CREATE TABLE IF NOT EXISTS article_reads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT NOT NULL,
  reader_ip TEXT NOT NULL,
  user_agent TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(article_id, reader_ip),
  FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_article_reads_article ON article_reads(article_id);
CREATE INDEX IF NOT EXISTS idx_article_reads_ip ON article_reads(reader_ip);
