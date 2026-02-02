import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

let db: Database.Database | null = null;

export function initDB() {
  if (db) return db;
  
  const dbPath = process.env.DATABASE_PATH || path.join(process.cwd(), 'data', 'moltpad.db');
  
  // Ensure data directory exists
  const dir = path.dirname(dbPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  
  db = new Database(dbPath);
  
  // Enable WAL mode for better performance
  db.pragma('journal_mode = WAL');
  
  // Create tables
  createTables();
  
  console.log('Database initialized at:', dbPath);
  return db;
}

export function getDb() {
  if (!db) {
    return initDB();
  }
  return db;
}

function createTables() {
  if (!db) return;
  
  // Agents table
  db.exec(`
    CREATE TABLE IF NOT EXISTS agents (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      handle TEXT UNIQUE NOT NULL,
      bio TEXT DEFAULT '',
      agent_type TEXT DEFAULT 'writer',
      verified INTEGER DEFAULT 0,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      followers_count INTEGER DEFAULT 0,
      following_count INTEGER DEFAULT 0
    )
  `);
  
  // Articles table
  db.exec(`
    CREATE TABLE IF NOT EXISTS articles (
      id TEXT PRIMARY KEY,
      slug TEXT UNIQUE NOT NULL,
      title TEXT NOT NULL,
      content TEXT NOT NULL,
      summary TEXT,
      category TEXT,
      tags TEXT,
      agent_id TEXT,
      likes INTEGER DEFAULT 0,
      comments INTEGER DEFAULT 0,
      edit_count INTEGER DEFAULT 1,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
    )
  `);
  
  // Follows table
  db.exec(`
    CREATE TABLE IF NOT EXISTS follows (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      follower_id TEXT NOT NULL,
      following_id TEXT NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(follower_id, following_id),
      FOREIGN KEY (follower_id) REFERENCES agents(id) ON DELETE CASCADE,
      FOREIGN KEY (following_id) REFERENCES agents(id) ON DELETE CASCADE
    )
  `);
  
  // Create indexes
  db.exec('CREATE INDEX IF NOT EXISTS idx_articles_agent ON articles(agent_id)');
  db.exec('CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)');
  db.exec('CREATE INDEX IF NOT EXISTS idx_follows_follower ON follows(follower_id)');
  db.exec('CREATE INDEX IF NOT EXISTS idx_follows_following ON follows(following_id)');
  
  console.log('Tables created successfully');
}
