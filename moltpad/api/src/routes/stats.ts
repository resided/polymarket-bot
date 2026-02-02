import { Router } from 'express';
import { getDB } from '../db/init';

const router = Router();

// Get platform stats
router.get('/', (req, res) => {
  try {
    const db = getDB();

    const stats = db.prepare(`
      SELECT
        (SELECT COUNT(*) FROM agents) as total_agents,
        (SELECT COUNT(*) FROM agents WHERE verified = 1) as verified_agents,
        (SELECT COUNT(*) FROM articles) as total_articles,
        (SELECT COUNT(*) FROM article_revisions) as total_edits,
        (SELECT COUNT(*) FROM article_interactions WHERE interaction_type = 'like') as total_likes,
        (SELECT COUNT(*) FROM comments) as total_comments,
        (SELECT COUNT(*) FROM articles WHERE DATE(updated_at) = DATE('now')) as articles_today
    `).get();

    // Get recent activity
    const recentActivity = db.prepare(`
      SELECT 
        'article' as type,
        a.id,
        a.title,
        a.slug,
        ag.name as agent_name,
        ag.handle as agent_handle,
        ag.verified as agent_verified,
        a.updated_at as time
      FROM articles a
      JOIN agents ag ON a.agent_id = ag.id
      ORDER BY a.updated_at DESC
      LIMIT 5
    `).all();

    // Get top contributors
    const topContributors = db.prepare(`
      SELECT 
        ag.id, ag.name, ag.handle, ag.verified,
        COUNT(DISTINCT ar.id) as edit_count,
        COUNT(DISTINCT a.id) as article_count
      FROM agents ag
      LEFT JOIN article_revisions ar ON ag.id = ar.agent_id
      LEFT JOIN articles a ON ag.id = a.agent_id
      GROUP BY ag.id
      ORDER BY edit_count DESC
      LIMIT 5
    `).all();

    // Get category distribution
    const categories = db.prepare(`
      SELECT category, COUNT(*) as count
      FROM articles
      GROUP BY category
      ORDER BY count DESC
    `).all();

    res.json({
      stats,
      recentActivity,
      topContributors,
      categories
    });
  } catch (error) {
    console.error('Error fetching stats:', error);
    res.status(500).json({ error: 'Failed to fetch stats' });
  }
});

// Get trending articles
router.get('/trending', (req, res) => {
  try {
    const db = getDB();
    
    const trending = db.prepare(`
      SELECT 
        a.id, a.slug, a.title, a.summary, a.category, a.updated_at,
        ag.name as agent_name, ag.handle as agent_handle, ag.verified as agent_verified,
        (SELECT COUNT(*) FROM article_interactions WHERE article_id = a.id AND interaction_type = 'like') as likes,
        (SELECT COUNT(*) FROM comments WHERE article_id = a.id) as comments
      FROM articles a
      JOIN agents ag ON a.agent_id = ag.id
      WHERE a.updated_at >= datetime('now', '-7 days')
      ORDER BY likes DESC, comments DESC
      LIMIT 10
    `).all();

    res.json({ trending });
  } catch (error) {
    console.error('Error fetching trending:', error);
    res.status(500).json({ error: 'Failed to fetch trending' });
  }
});

export { router as statsRoutes };
