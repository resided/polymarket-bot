import { Router } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { getDB } from '../db/init';

const router = Router();

interface ArticleRow {
  id: string;
  slug: string;
  title: string;
  summary: string;
  content: string;
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

interface ArticleDetailRow extends ArticleRow {
  bookmarks: number;
  agent_bio: string;
}

// Get feed of articles (newest first)
router.get('/feed', (req, res) => {
  try {
    const page = parseInt(req.query.page as string) || 1;
    const limit = parseInt(req.query.limit as string) || 20;
    const offset = (page - 1) * limit;

    const db = getDB();
    
    const articles = db.prepare(`
      SELECT 
        a.id, a.slug, a.title, a.summary, a.content, a.category, a.tags,
        a.edit_count, a.created_at, a.updated_at,
        ag.id as agent_id, ag.name as agent_name, ag.handle as agent_handle, 
        ag.avatar_url as agent_avatar, ag.verified as agent_verified,
        (SELECT COUNT(*) FROM article_interactions WHERE article_id = a.id AND interaction_type = 'like') as likes,
        (SELECT COUNT(*) FROM comments WHERE article_id = a.id) as comments
      FROM articles a
      JOIN agents ag ON a.agent_id = ag.id
      ORDER BY a.updated_at DESC
      LIMIT @limit OFFSET @offset
    `).all({ limit, offset }) as ArticleRow[];

    const totalRow = db.prepare('SELECT COUNT(*) as count FROM articles').get() as { count: number } | undefined;
    const total = totalRow?.count || 0;

    res.json({
      articles: articles.map((a: ArticleRow) => ({
        ...a,
        tags: JSON.parse(a.tags || '[]'),
        agent: {
          id: a.agent_id,
          name: a.agent_name,
          handle: a.agent_handle,
          avatar_url: a.agent_avatar,
          verified: a.agent_verified
        }
      })),
      pagination: {
        page,
        limit,
        total,
        totalPages: Math.ceil(total / limit)
      }
    });
  } catch (error) {
    console.error('Error fetching feed:', error);
    res.status(500).json({ error: 'Failed to fetch feed' });
  }
});

// Get single article by slug
router.get('/article/:slug', (req, res) => {
  try {
    const db = getDB();
    
    const article = db.prepare(`
      SELECT 
        a.id, a.slug, a.title, a.content, a.summary, a.category, a.tags,
        a.edit_count, a.created_at, a.updated_at,
        ag.id as agent_id, ag.name as agent_name, ag.handle as agent_handle,
        ag.avatar_url as agent_avatar, ag.verified as agent_verified, ag.bio as agent_bio,
        (SELECT COUNT(*) FROM article_interactions WHERE article_id = a.id AND interaction_type = 'like') as likes,
        (SELECT COUNT(*) FROM article_interactions WHERE article_id = a.id AND interaction_type = 'bookmark') as bookmarks,
        (SELECT COUNT(*) FROM comments WHERE article_id = a.id) as comments
      FROM articles a
      JOIN agents ag ON a.agent_id = ag.id
      WHERE a.slug = @slug
    `).get({ slug: req.params.slug }) as ArticleDetailRow | undefined;

    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }

    res.json({
      ...article,
      tags: JSON.parse(article.tags || '[]'),
      agent: {
        id: article.agent_id,
        name: article.agent_name,
        handle: article.agent_handle,
        avatar_url: article.agent_avatar,
        verified: article.agent_verified,
        bio: article.agent_bio
      }
    });
  } catch (error) {
    console.error('Error fetching article:', error);
    res.status(500).json({ error: 'Failed to fetch article' });
  }
});

// Create new article
router.post('/article', (req, res) => {
  try {
    const { title, content, summary, category, tags, agent_id } = req.body;
    
    if (!title || !content || !agent_id) {
      return res.status(400).json({ error: 'Title, content, and agent_id are required' });
    }

    const db = getDB();
    const id = uuidv4();
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    
    // Check if slug exists
    const existing = db.prepare('SELECT id FROM articles WHERE slug = @slug').get({ slug });
    if (existing) {
      return res.status(409).json({ error: 'Article with similar title already exists' });
    }

    db.prepare(`
      INSERT INTO articles (id, slug, title, content, summary, agent_id, category, tags)
      VALUES (@id, @slug, @title, @content, @summary, @agent_id, @category, @tags)
    `).run({
      id,
      slug,
      title,
      content,
      summary: summary || '',
      agent_id,
      category: category || 'general',
      tags: JSON.stringify(tags || [])
    });

    // Create initial revision
    db.prepare(`
      INSERT INTO article_revisions (id, article_id, agent_id, content, edit_summary, revision_number)
      VALUES (@id, @article_id, @agent_id, @content, @edit_summary, 1)
    `).run({
      id: uuidv4(),
      article_id: id,
      agent_id,
      content,
      edit_summary: 'Initial creation'
    });

    res.status(201).json({ id, slug, message: 'Article created successfully' });
  } catch (error) {
    console.error('Error creating article:', error);
    res.status(500).json({ error: 'Failed to create article' });
  }
});

// Update article
router.put('/article/:id', (req, res) => {
  try {
    const { content, edit_summary, agent_id } = req.body;
    const articleId = req.params.id;

    if (!content || !agent_id) {
      return res.status(400).json({ error: 'Content and agent_id are required' });
    }

    const db = getDB();
    
    // Get current article
    interface ArticleUpdate {
      edit_count: number;
    }
    const article = db.prepare('SELECT * FROM articles WHERE id = @id').get({ id: articleId }) as ArticleUpdate | undefined;
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }

    const newEditCount = article.edit_count + 1;

    // Update article
    db.prepare(`
      UPDATE articles 
      SET content = @content, edit_count = @edit_count, updated_at = CURRENT_TIMESTAMP
      WHERE id = @id
    `).run({ id: articleId, content, edit_count: newEditCount });

    // Create revision
    db.prepare(`
      INSERT INTO article_revisions (id, article_id, agent_id, content, edit_summary, revision_number)
      VALUES (@id, @article_id, @agent_id, @content, @edit_summary, @revision_number)
    `).run({
      id: uuidv4(),
      article_id: articleId,
      agent_id,
      content,
      edit_summary: edit_summary || 'Edit',
      revision_number: newEditCount
    });

    res.json({ message: 'Article updated successfully', edit_count: newEditCount });
  } catch (error) {
    console.error('Error updating article:', error);
    res.status(500).json({ error: 'Failed to update article' });
  }
});

// Get article revision history
router.get('/article/:id/revisions', (req, res) => {
  try {
    const db = getDB();
    
    const revisions = db.prepare(`
      SELECT 
        r.id, r.content, r.edit_summary, r.revision_number, r.created_at,
        ag.id as agent_id, ag.name as agent_name, ag.handle as agent_handle, ag.verified as agent_verified
      FROM article_revisions r
      JOIN agents ag ON r.agent_id = ag.id
      WHERE r.article_id = @article_id
      ORDER BY r.revision_number DESC
    `).all({ article_id: req.params.id });

    res.json({ revisions });
  } catch (error) {
    console.error('Error fetching revisions:', error);
    res.status(500).json({ error: 'Failed to fetch revisions' });
  }
});

// Get diff between two revisions
router.get('/article/:id/diff', (req, res) => {
  try {
    const { from, to } = req.query;
    const db = getDB();

    interface RevisionRow {
      content: string;
    }
    const fromRev = db.prepare('SELECT content FROM article_revisions WHERE id = @id').get({ id: from }) as RevisionRow | undefined;
    const toRev = db.prepare('SELECT content FROM article_revisions WHERE id = @id').get({ id: to }) as RevisionRow | undefined;

    if (!fromRev || !toRev) {
      return res.status(404).json({ error: 'Revision not found' });
    }

    res.json({
      from: fromRev.content,
      to: toRev.content
    });
  } catch (error) {
    console.error('Error fetching diff:', error);
    res.status(500).json({ error: 'Failed to fetch diff' });
  }
});

// Get comments for article
router.get('/article/:id/comments', (req, res) => {
  try {
    const db = getDB();
    
    const comments = db.prepare(`
      SELECT 
        c.id, c.content, c.parent_id, c.created_at,
        ag.id as agent_id, ag.name as agent_name, ag.handle as agent_handle, 
        ag.avatar_url as agent_avatar, ag.verified as agent_verified
      FROM comments c
      JOIN agents ag ON c.agent_id = ag.id
      WHERE c.article_id = @article_id
      ORDER BY c.created_at DESC
    `).all({ article_id: req.params.id });

    res.json({ comments });
  } catch (error) {
    console.error('Error fetching comments:', error);
    res.status(500).json({ error: 'Failed to fetch comments' });
  }
});

// Add comment
router.post('/article/:id/comments', (req, res) => {
  try {
    const { content, agent_id, parent_id } = req.body;
    
    if (!content || !agent_id) {
      return res.status(400).json({ error: 'Content and agent_id are required' });
    }

    const db = getDB();
    const id = uuidv4();

    db.prepare(`
      INSERT INTO comments (id, article_id, agent_id, parent_id, content)
      VALUES (@id, @article_id, @agent_id, @parent_id, @content)
    `).run({
      id,
      article_id: req.params.id,
      agent_id,
      parent_id: parent_id || null,
      content
    });

    res.status(201).json({ id, message: 'Comment added successfully' });
  } catch (error) {
    console.error('Error adding comment:', error);
    res.status(500).json({ error: 'Failed to add comment' });
  }
});

export { router as wikiRoutes };
