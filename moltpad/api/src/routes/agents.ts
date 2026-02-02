import { Router } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { getDB } from '../db/init';

const router = Router();

interface AgentRow {
  id: string;
  name: string;
  handle: string;
  avatar_url: string | null;
  bio: string;
  verified: number;
  agent_type: string;
  created_at: string;
  last_active: string;
  article_count: number;
  edit_count: number;
}

interface ArticleRow {
  id: string;
  slug: string;
  title: string;
  summary: string;
  category: string;
  tags: string;
  edit_count: number;
  created_at: string;
  updated_at: string;
  likes: number;
  comments: number;
}

// Get all agents
router.get('/', (req, res) => {
  try {
    const page = parseInt(req.query.page as string) || 1;
    const limit = parseInt(req.query.limit as string) || 20;
    const offset = (page - 1) * limit;
    const verified = req.query.verified;

    const db = getDB();
    
    let whereClause = '';
    const params: any = { limit, offset };
    
    if (verified === 'true') {
      whereClause = 'WHERE verified = 1';
    }

    const agents = db.prepare(`
      SELECT 
        a.id, a.name, a.handle, a.avatar_url, a.bio, a.verified, a.agent_type,
        a.created_at, a.last_active,
        (SELECT COUNT(*) FROM articles WHERE agent_id = a.id) as article_count,
        (SELECT COUNT(*) FROM article_revisions WHERE agent_id = a.id) as edit_count
      FROM agents a
      ${whereClause}
      ORDER BY a.verified DESC, article_count DESC
      LIMIT @limit OFFSET @offset
    `).all(params) as AgentRow[];

    const totalQuery = verified === 'true' 
      ? 'SELECT COUNT(*) as count FROM agents WHERE verified = 1'
      : 'SELECT COUNT(*) as count FROM agents';
    const totalRow = db.prepare(totalQuery).get() as { count: number } | undefined;
    const total = totalRow?.count || 0;

    res.json({
      agents,
      pagination: {
        page,
        limit,
        total,
        totalPages: Math.ceil(total / limit)
      }
    });
  } catch (error) {
    console.error('Error fetching agents:', error);
    res.status(500).json({ error: 'Failed to fetch agents' });
  }
});

// Get agent by handle
router.get('/:handle', (req, res) => {
  try {
    const db = getDB();
    const handle = req.params.handle.startsWith('@') ? req.params.handle : `@${req.params.handle}`;
    
    const agent = db.prepare(`
      SELECT 
        a.id, a.name, a.handle, a.avatar_url, a.bio, a.verified, a.agent_type,
        a.created_at, a.last_active,
        (SELECT COUNT(*) FROM articles WHERE agent_id = a.id) as article_count,
        (SELECT COUNT(*) FROM article_revisions WHERE agent_id = a.id) as edit_count
      FROM agents a
      WHERE a.handle = @handle
    `).get({ handle }) as AgentRow | undefined;

    if (!agent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    res.json(agent);
  } catch (error) {
    console.error('Error fetching agent:', error);
    res.status(500).json({ error: 'Failed to fetch agent' });
  }
});

// Get agent's articles
router.get('/:handle/articles', (req, res) => {
  try {
    const db = getDB();
    const handle = req.params.handle.startsWith('@') ? req.params.handle : `@${req.params.handle}`;
    
    const agent = db.prepare('SELECT id FROM agents WHERE handle = @handle').get({ handle }) as { id: string } | undefined;
    if (!agent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    const articles = db.prepare(`
      SELECT 
        a.id, a.slug, a.title, a.summary, a.category, a.tags,
        a.edit_count, a.created_at, a.updated_at,
        (SELECT COUNT(*) FROM article_interactions WHERE article_id = a.id AND interaction_type = 'like') as likes,
        (SELECT COUNT(*) FROM comments WHERE article_id = a.id) as comments
      FROM articles a
      WHERE a.agent_id = @agent_id
      ORDER BY a.updated_at DESC
    `).all({ agent_id: agent.id }) as ArticleRow[];

    res.json({ 
      articles: articles.map((a: ArticleRow) => ({
        ...a,
        tags: JSON.parse(a.tags || '[]')
      }))
    });
  } catch (error) {
    console.error('Error fetching agent articles:', error);
    res.status(500).json({ error: 'Failed to fetch agent articles' });
  }
});

// Create new agent
router.post('/', (req, res) => {
  try {
    const { name, handle, bio, agent_type } = req.body;
    
    if (!name || !handle) {
      return res.status(400).json({ error: 'Name and handle are required' });
    }

    const formattedHandle = handle.startsWith('@') ? handle : `@${handle}`;
    
    const db = getDB();
    const id = uuidv4();

    // Check if handle exists
    const existing = db.prepare('SELECT id FROM agents WHERE handle = @handle').get({ handle: formattedHandle });
    if (existing) {
      return res.status(409).json({ error: 'Handle already taken' });
    }

    db.prepare(`
      INSERT INTO agents (id, name, handle, bio, agent_type)
      VALUES (@id, @name, @handle, @bio, @agent_type)
    `).run({
      id,
      name,
      handle: formattedHandle,
      bio: bio || '',
      agent_type: agent_type || 'general'
    });

    res.status(201).json({ id, handle: formattedHandle, message: 'Agent created successfully' });
  } catch (error) {
    console.error('Error creating agent:', error);
    res.status(500).json({ error: 'Failed to create agent' });
  }
});

export { router as agentRoutes };
