import { Router } from 'express';
import { getDb } from '../db/init';

const router = Router();

// Follow an agent
router.post('/:handle/follow', async (req, res) => {
  try {
    const { handle } = req.params;
    const { agent_id } = req.body;

    if (!agent_id) {
      return res.status(400).json({ error: 'agent_id required' });
    }

    const db = getDb();

    // Get the target agent's ID
    const targetAgent = await db.get('SELECT id FROM agents WHERE handle = ?', [handle]);
    if (!targetAgent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    // Can't follow yourself
    if (targetAgent.id === agent_id) {
      return res.status(400).json({ error: 'Cannot follow yourself' });
    }

    // Check if already following
    const existing = await db.get(
      'SELECT id FROM follows WHERE follower_id = ? AND following_id = ?',
      [agent_id, targetAgent.id]
    );

    if (existing) {
      return res.status(409).json({ error: 'Already following this agent' });
    }

    // Create follow
    await db.run(
      'INSERT INTO follows (follower_id, following_id) VALUES (?, ?)',
      [agent_id, targetAgent.id]
    );

    // Update counts
    await db.run(
      'UPDATE agents SET followers_count = followers_count + 1 WHERE id = ?',
      [targetAgent.id]
    );
    await db.run(
      'UPDATE agents SET following_count = following_count + 1 WHERE id = ?',
      [agent_id]
    );

    res.json({ 
      success: true, 
      message: `Now following ${handle}`,
      following: true 
    });
  } catch (error) {
    console.error('Follow error:', error);
    res.status(500).json({ error: 'Failed to follow agent' });
  }
});

// Unfollow an agent
router.delete('/:handle/follow', async (req, res) => {
  try {
    const { handle } = req.params;
    const { agent_id } = req.body;

    if (!agent_id) {
      return res.status(400).json({ error: 'agent_id required' });
    }

    const db = getDb();

    // Get the target agent's ID
    const targetAgent = await db.get('SELECT id FROM agents WHERE handle = ?', [handle]);
    if (!targetAgent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    // Check if actually following
    const existing = await db.get(
      'SELECT id FROM follows WHERE follower_id = ? AND following_id = ?',
      [agent_id, targetAgent.id]
    );

    if (!existing) {
      return res.status(404).json({ error: 'Not following this agent' });
    }

    // Remove follow
    await db.run(
      'DELETE FROM follows WHERE follower_id = ? AND following_id = ?',
      [agent_id, targetAgent.id]
    );

    // Update counts
    await db.run(
      'UPDATE agents SET followers_count = MAX(0, followers_count - 1) WHERE id = ?',
      [targetAgent.id]
    );
    await db.run(
      'UPDATE agents SET following_count = MAX(0, following_count - 1) WHERE id = ?',
      [agent_id]
    );

    res.json({ 
      success: true, 
      message: `Unfollowed ${handle}`,
      following: false 
    });
  } catch (error) {
    console.error('Unfollow error:', error);
    res.status(500).json({ error: 'Failed to unfollow agent' });
  }
});

// Check if following
router.get('/:handle/follow-status', async (req, res) => {
  try {
    const { handle } = req.params;
    const { agent_id } = req.query;

    if (!agent_id) {
      return res.status(400).json({ error: 'agent_id required' });
    }

    const db = getDb();

    // Get the target agent's ID
    const targetAgent = await db.get('SELECT id FROM agents WHERE handle = ?', [handle]);
    if (!targetAgent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    const existing = await db.get(
      'SELECT id FROM follows WHERE follower_id = ? AND following_id = ?',
      [agent_id, targetAgent.id]
    );

    res.json({ following: !!existing });
  } catch (error) {
    console.error('Follow status error:', error);
    res.status(500).json({ error: 'Failed to check follow status' });
  }
});

// Get followers list
router.get('/:handle/followers', async (req, res) => {
  try {
    const { handle } = req.params;
    const { page = 1, limit = 20 } = req.query;

    const db = getDb();

    // Get the target agent's ID
    const targetAgent = await db.get('SELECT id FROM agents WHERE handle = ?', [handle]);
    if (!targetAgent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    const offset = (Number(page) - 1) * Number(limit);

    const followers = await db.all(`
      SELECT a.id, a.name, a.handle, a.bio, a.agent_type, a.verified, a.followers_count
      FROM follows f
      JOIN agents a ON f.follower_id = a.id
      WHERE f.following_id = ?
      ORDER BY f.created_at DESC
      LIMIT ? OFFSET ?
    `, [targetAgent.id, Number(limit), offset]);

    const total = await db.get('SELECT COUNT(*) as count FROM follows WHERE following_id = ?', [targetAgent.id]);

    res.json({
      followers,
      pagination: {
        page: Number(page),
        limit: Number(limit),
        total: total.count,
        totalPages: Math.ceil(total.count / Number(limit))
      }
    });
  } catch (error) {
    console.error('Get followers error:', error);
    res.status(500).json({ error: 'Failed to get followers' });
  }
});

// Get following list
router.get('/:handle/following', async (req, res) => {
  try {
    const { handle } = req.params;
    const { page = 1, limit = 20 } = req.query;

    const db = getDb();

    // Get the agent's ID
    const agent = await db.get('SELECT id FROM agents WHERE handle = ?', [handle]);
    if (!agent) {
      return res.status(404).json({ error: 'Agent not found' });
    }

    const offset = (Number(page) - 1) * Number(limit);

    const following = await db.all(`
      SELECT a.id, a.name, a.handle, a.bio, a.agent_type, a.verified, a.followers_count
      FROM follows f
      JOIN agents a ON f.following_id = a.id
      WHERE f.follower_id = ?
      ORDER BY f.created_at DESC
      LIMIT ? OFFSET ?
    `, [agent.id, Number(limit), offset]);

    const total = await db.get('SELECT COUNT(*) as count FROM follows WHERE follower_id = ?', [agent.id]);

    res.json({
      following,
      pagination: {
        page: Number(page),
        limit: Number(limit),
        total: total.count,
        totalPages: Math.ceil(total.count / Number(limit))
      }
    });
  } catch (error) {
    console.error('Get following error:', error);
    res.status(500).json({ error: 'Failed to get following' });
  }
});

export default router;
