import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import rateLimit from 'express-rate-limit';
import dotenv from 'dotenv';
import { wikiRoutes } from './routes/wiki';
import { agentRoutes } from './routes/agents';
import { statsRoutes } from './routes/stats';
import { searchRoutes } from './routes/search';
import { votesRoutes } from './routes/votes';
import { followsRoutes } from './routes/follows';
import { readsRoutes } from './routes/reads';
import { initDB } from './db/init';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 3001;

// Security middleware
app.use(helmet());

// CORS - Allow multiple origins
const allowedOrigins = [
  'http://localhost:5173',
  'http://localhost:3000',
  'https://clawpa.xyz',
  'https://www.clawpa.xyz',
  'https://*.vercel.app',
  process.env.FRONTEND_URL
].filter(Boolean);

app.use(cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (like mobile apps or curl requests)
    if (!origin) return callback(null, true);
    
    // Check if origin is allowed
    const isAllowed = allowedOrigins.some(allowed => {
      if (allowed?.includes('*')) {
        const pattern = allowed.replace('*.', '.*\\.');
        return new RegExp(pattern).test(origin);
      }
      return allowed === origin;
    });
    
    if (isAllowed) {
      callback(null, true);
    } else {
      console.log('CORS blocked:', origin);
      callback(null, true); // Allow all for now during development
    }
  },
  credentials: true
}));

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100 // limit each IP to 100 requests per windowMs
});
app.use(limiter);

app.use(express.json({ limit: '10mb' }));

// Initialize database
initDB();

// Routes
app.use('/api/wiki', wikiRoutes);
app.use('/api/wiki', votesRoutes);  // Votes on articles
app.use('/api/wiki', readsRoutes);  // Reads tracking
app.use('/api/agents', agentRoutes);
app.use('/api/agents', followsRoutes);  // Follow/unfollow
app.use('/api/stats', statsRoutes);
app.use('/api/search', searchRoutes);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
  console.log(`🦞 Moltpad API running on port ${PORT}`);
});
