import { Router } from 'express';
import { getDb } from '../db/init';

const router = Router();

// Increment article reads
router.post('/:slug/read', async (req, res) => {
  try {
    const { slug } = req.params;
    const readerIp = req.ip || req.socket.remoteAddress || 'unknown';
    const userAgent = req.headers['user-agent'] || 'unknown';
    
    const db = getDb();
    
    // Get article ID
    const article = await db.get('SELECT id FROM articles WHERE slug = ?', [slug]);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }
    
    // Check if this IP has already read this article (simple deduplication)
    const existingRead = await db.get(
      'SELECT id FROM article_reads WHERE article_id = ? AND reader_ip = ?',
      [article.id, readerIp]
    );
    
    if (existingRead) {
      // Already read, just return current count
      const currentReads = await db.get('SELECT reads FROM articles WHERE id = ?', [article.id]);
      return res.json({ 
        success: true, 
        reads: currentReads?.reads || 0,
        newRead: false,
        message: 'Already counted this read'
      });
    }
    
    // Record this unique reader
    await db.run(
      'INSERT INTO article_reads (article_id, reader_ip, user_agent) VALUES (?, ?, ?)',
      [article.id, readerIp, userAgent]
    );
    
    // Increment read count
    await db.run(
      'UPDATE articles SET reads = reads + 1 WHERE id = ?',
      [article.id]
    );
    
    // Get updated count
    const updated = await db.get('SELECT reads FROM articles WHERE id = ?', [article.id]);
    
    res.json({ 
      success: true, 
      reads: updated?.reads || 0,
      newRead: true,
      message: 'Read counted'
    });
  } catch (error) {
    console.error('Read increment error:', error);
    res.status(500).json({ error: 'Failed to increment reads' });
  }
});

// Get article reads
router.get('/:slug/reads', async (req, res) => {
  try {
    const { slug } = req.params;
    
    const db = getDb();
    
    const article = await db.get('SELECT reads FROM articles WHERE slug = ?', [slug]);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }
    
    res.json({ reads: article.reads || 0 });
  } catch (error) {
    console.error('Get reads error:', error);
    res.status(500).json({ error: 'Failed to get reads' });
  }
});

export default router;
