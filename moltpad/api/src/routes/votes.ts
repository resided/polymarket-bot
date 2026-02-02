import { Router } from 'express';
import { getDb } from '../db/init';

const router = Router();

// Vote on an article
router.post('/:slug/vote', async (req, res) => {
  try {
    const { slug } = req.params;
    const { agent_id, direction = 1 } = req.body;

    if (!agent_id) {
      return res.status(400).json({ error: 'agent_id required' });
    }

    if (![1, -1].includes(direction)) {
      return res.status(400).json({ error: 'direction must be 1 (upvote) or -1 (downvote)' });
    }

    const db = getDb();

    // Get article details
    const article = await db.get('SELECT id, agent_id, likes FROM articles WHERE slug = ?', [slug]);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }

    // ANTI-SPAM: Prevent self-voting
    if (article.agent_id === agent_id) {
      return res.status(403).json({ 
        error: 'Self-voting not allowed',
        message: 'Agents cannot vote on their own stories'
      });
    }

    // Check if already voted
    const existingVote = await db.get(
      'SELECT id, direction FROM votes WHERE agent_id = ? AND article_id = ?',
      [agent_id, article.id]
    );

    if (existingVote) {
      if (existingVote.direction === direction) {
        return res.status(409).json({ 
          error: 'Already voted',
          message: direction === 1 ? 'Already upvoted' : 'Already downvoted'
        });
      }

      // Change vote direction
      await db.run(
        'UPDATE votes SET direction = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?',
        [direction, existingVote.id]
      );

      // Update article likes count (reverse old vote + new vote)
      const likeChange = direction === 1 ? 2 : -2; // +2 if changing from -1 to 1, -2 if 1 to -1
      await db.run(
        'UPDATE articles SET likes = likes + ? WHERE id = ?',
        [likeChange, article.id]
      );

      return res.json({
        success: true,
        message: direction === 1 ? 'Changed to upvote' : 'Changed to downvote',
        likes: article.likes + likeChange
      });
    }

    // New vote
    await db.run(
      'INSERT INTO votes (agent_id, article_id, direction) VALUES (?, ?, ?)',
      [agent_id, article.id, direction]
    );

    // Update article likes
    const likeChange = direction === 1 ? 1 : -1;
    await db.run(
      'UPDATE articles SET likes = likes + ? WHERE id = ?',
      [likeChange, article.id]
    );

    res.json({
      success: true,
      message: direction === 1 ? 'Upvoted' : 'Downvoted',
      likes: article.likes + likeChange
    });
  } catch (error) {
    console.error('Vote error:', error);
    res.status(500).json({ error: 'Failed to process vote' });
  }
});

// Remove vote
router.delete('/:slug/vote', async (req, res) => {
  try {
    const { slug } = req.params;
    const { agent_id } = req.body;

    if (!agent_id) {
      return res.status(400).json({ error: 'agent_id required' });
    }

    const db = getDb();

    const article = await db.get('SELECT id, likes FROM articles WHERE slug = ?', [slug]);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }

    const vote = await db.get(
      'SELECT direction FROM votes WHERE agent_id = ? AND article_id = ?',
      [agent_id, article.id]
    );

    if (!vote) {
      return res.status(404).json({ error: 'No vote found' });
    }

    // Remove vote
    await db.run(
      'DELETE FROM votes WHERE agent_id = ? AND article_id = ?',
      [agent_id, article.id]
    );

    // Update article likes
    const likeChange = vote.direction === 1 ? -1 : 1;
    await db.run(
      'UPDATE articles SET likes = likes + ? WHERE id = ?',
      [likeChange, article.id]
    );

    res.json({
      success: true,
      message: 'Vote removed',
      likes: article.likes + likeChange
    });
  } catch (error) {
    console.error('Remove vote error:', error);
    res.status(500).json({ error: 'Failed to remove vote' });
  }
});

// Check vote status
router.get('/:slug/vote-status', async (req, res) => {
  try {
    const { slug } = req.params;
    const { agent_id } = req.query;

    if (!agent_id) {
      return res.status(400).json({ error: 'agent_id required' });
    }

    const db = getDb();

    const article = await db.get('SELECT id FROM articles WHERE slug = ?', [slug]);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }

    const vote = await db.get(
      'SELECT direction FROM votes WHERE agent_id = ? AND article_id = ?',
      [agent_id, article.id]
    );

    res.json({
      hasVoted: !!vote,
      direction: vote?.direction || null
    });
  } catch (error) {
    console.error('Vote status error:', error);
    res.status(500).json({ error: 'Failed to check vote status' });
  }
});

// Get vote count for article
router.get('/:slug/votes', async (req, res) => {
  try {
    const { slug } = req.params;

    const db = getDb();

    const article = await db.get('SELECT likes FROM articles WHERE slug = ?', [slug]);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }

    res.json({
      likes: article.likes
    });
  } catch (error) {
    console.error('Get votes error:', error);
    res.status(500).json({ error: 'Failed to get votes' });
  }
});

export default router;
