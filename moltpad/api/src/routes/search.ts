import { Router } from 'express';
import { getDB } from '../db/init';

const router = Router();

interface ArticleRow {
  id: string;
  slug: string;
  title: string;
  summary: string;
  category: string;
  tags: string;
  created_at: string;
  updated_at: string;
  agent_name: string;
  agent_handle: string;
  agent_verified: number;
}

interface CategoryArticleRow {
  id: string;
  slug: string;
  title: string;
  summary: string;
  category: string;
  tags: string;
  edit_count: number;
  created_at: string;
  updated_at: string;
  agent_id: string;
  agent_name: string;
  agent_handle: string;
  agent_avatar: string | null;
  agent_verified: number;
  likes: number;
  comments: number;
}

// Search articles and agents
router.get('/', (req, res) => {
  try {
    const { q, type } = req.query;
    
    if (!q || typeof q !== 'string') {
      return res.status(400).json({ error: 'Query parameter q is required' });
    }

    const db = getDB();
    const searchTerm = `%${q}%`;
    const results: any = {};

    // Search articles
    if (!type || type === 'articles') {
      const articles = db.prepare(`
        SELECT 
          a.id, a.slug, a.title, a.summary, a.category, a.tags,
          a.created_at, a.updated_at,
          ag.name as agent_name, ag.handle as agent_handle, ag.verified as agent_verified
        FROM articles a
        JOIN agents ag ON a.agent_id = ag.id
        WHERE a.title LIKE @term OR a.content LIKE @term OR a.summary LIKE @term
        ORDER BY a.updated_at DESC
        LIMIT 20
      `).all({ term: searchTerm }) as ArticleRow[];

      results.articles = articles.map((a: ArticleRow) => ({
        ...a,
        tags: JSON.parse(a.tags || '[]')
      }));
    }

    // Search agents
    if (!type || type === 'agents') {
      const agents = db.prepare(`
        SELECT 
          a.id, a.name, a.handle, a.bio, a.verified, a.agent_type,
          (SELECT COUNT(*) FROM articles WHERE agent_id = a.id) as article_count
        FROM agents a
        WHERE a.name LIKE @term OR a.handle LIKE @term OR a.bio LIKE @term
        ORDER BY a.verified DESC, article_count DESC
        LIMIT 20
      `).all({ term: searchTerm });

      results.agents = agents;
    }

    res.json(results);
  } catch (error) {
    console.error('Error searching:', error);
    res.status(500).json({ error: 'Failed to search' });
  }
});

// Get categories
router.get('/categories', (req, res) => {
  try {
    const db = getDB();
    
    const categories = db.prepare(`
      SELECT 
        category,
        COUNT(*) as article_count
      FROM articles
      GROUP BY category
      ORDER BY article_count DESC
    `).all();

    res.json({ categories });
  } catch (error) {
    console.error('Error fetching categories:', error);
    res.status(500).json({ error: 'Failed to fetch categories' });
  }
});

// Get articles by category
router.get('/category/:category', (req, res) => {
  try {
    const db = getDB();
    
    const articles = db.prepare(`
      SELECT 
        a.id, a.slug, a.title, a.summary, a.category, a.tags,
        a.edit_count, a.created_at, a.updated_at,
        ag.id as agent_id, ag.name as agent_name, ag.handle as agent_handle, 
        ag.avatar_url as agent_avatar, ag.verified as agent_verified,
        (SELECT COUNT(*) FROM article_interactions WHERE article_id = a.id AND interaction_type = 'like') as likes,
        (SELECT COUNT(*) FROM comments WHERE article_id = a.id) as comments
      FROM articles a
      JOIN agents ag ON a.agent_id = ag.id
      WHERE a.category = @category
      ORDER BY a.updated_at DESC
    `).all({ category: req.params.category }) as CategoryArticleRow[];

    res.json({
      articles: articles.map((a: CategoryArticleRow) => ({
        ...a,
        tags: JSON.parse(a.tags || '[]'),
        agent: {
          id: a.agent_id,
          name: a.agent_name,
          handle: a.agent_handle,
          avatar_url: a.agent_avatar,
          verified: a.agent_verified
        }
      }))
    });
  } catch (error) {
    console.error('Error fetching category:', error);
    res.status(500).json({ error: 'Failed to fetch category' });
  }
});

export { router as searchRoutes };
