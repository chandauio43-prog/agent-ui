const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const path = require('path');
const { Groq } = require('groq-sdk');

const app = express();
const PORT = process.env.PORT || 10000;

// ---------- LOGGING ----------
console.log('Starting server...');
console.log('PORT:', PORT);
console.log('GROQ_API_KEY set?', !!process.env.GROQ_API_KEY);

// ---------- MIDDLEWARE ----------
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static(__dirname));

// ---------- HEALTH CHECK ----------
app.get('/health', (req, res) => {
  res.json({ status: 'ok', time: new Date().toISOString() });
});

// ---------- GROQ CLIENT ----------
let client = null;
try {
  if (process.env.GROQ_API_KEY) {
    client = new Groq({ apiKey: process.env.GROQ_API_KEY });
    console.log('✅ Groq client initialized');
  } else {
    console.warn('⚠️ GROQ_API_KEY not set. Agent will fail.');
  }
} catch (err) {
  console.error('❌ Failed to initialize Groq client:', err.message);
}

const WORKSPACE = '/tmp/agent_workspace';
const MAX_ITERATIONS = 10;

// Ensure workspace exists
fs.mkdir(WORKSPACE, { recursive: true }).catch(console.error);

// ---------- TOOLS ----------
const tools = {
  write_file: async (pathname, content) => {
    const full = path.join(WORKSPACE, pathname);
    await fs.mkdir(path.dirname(full), { recursive: true });
    await fs.writeFile(full, content, 'utf-8');
    return `Wrote ${pathname} (${content.length} chars)`;
  },
  read_file: async (pathname) => {
    const full = path.join(WORKSPACE, pathname);
    try {
      const content = await fs.readFile(full, 'utf-8');
      return content.slice(0, 2000);
    } catch {
      return `File not found: ${pathname}`;
    }
  },
  delete_file: async (pathname) => {
    // disabled for safety
    return 'Deletion disabled';
  },
  list_files: async () => {
    try {
      const items = await fs.readdir(WORKSPACE);
      return items.join('\n') || 'No files';
    } catch {
      return 'Folder not found';
    }
  },
  run_command: (cmd) => {
    return 'Command execution disabled';
  }
};

// ---------- AGENT LOOP ----------
async function* agentLoop(prompt) {
  if (!client) {
    yield { error: 'GROQ_API_KEY not set. Please set it in environment variables.' };
    return;
  }

  const messages = [
    {
      role: 'system',
      content: `You are an autonomous developer. Workspace: ${WORKSPACE}
Tools: write_file, read_file, delete_file, list_files, run_command.
Output JSON: {"tool":"write_file","path":"x","content":"y"} or {"done":"message"}`
    },
    { role: 'user', content: prompt }
  ];

  for (let i = 0; i < MAX_ITERATIONS; i++) {
    try {
      const response = await client.chat.completions.create({
        model: 'llama-3.3-70b-versatile',
        messages,
        temperature: 0.3,
        response_format: { type: 'json_object' }
      });
      let action;
      try {
        action = JSON.parse(response.choices[0].message.content);
      } catch {
        yield { error: 'Invalid JSON from LLM' };
        break;
      }

      if (action.done) {
        yield { done: action.done };
        break;
      }

      const toolName = action.tool;
      if (!tools[toolName]) {
        yield { error: `Unknown tool: ${toolName}` };
        break;
      }

      let result;
      if (toolName === 'write_file') {
        result = await tools[toolName](action.path, action.content);
      } else if (toolName === 'run_command') {
        result = tools[toolName](action.cmd);
      } else {
        result = await tools[toolName](action.path || '.');
      }

      yield { step: i+1, action, result };

      messages.push({ role: 'assistant', content: JSON.stringify(action) });
      messages.push({ role: 'user', content: `Result: ${result}` });
    } catch (err) {
      yield { error: err.message };
      break;
    }
  }
}

// ---------- API ROUTES ----------
app.post('/api/agent', async (req, res) => {
  const { prompt } = req.body;
  if (!prompt) {
    return res.status(400).json({ error: 'No prompt' });
  }

  const results = [];
  for await (const chunk of agentLoop(prompt)) {
    results.push(chunk);
  }
  res.json(results);
});

app.get('/api/files', async (req, res) => {
  try {
    const items = await fs.readdir(WORKSPACE);
    const fileList = [];
    for (const item of items) {
      const stat = await fs.stat(path.join(WORKSPACE, item));
      if (stat.isFile()) fileList.push(item);
    }
    res.json(fileList);
  } catch {
    res.json([]);
  }
});

// Serve admin.html
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'admin.html'));
});

// ---------- START ----------
app.listen(PORT, '0.0.0.0', () => {
  console.log(`🚀 Server running on port ${PORT}`);
  console.log(`📁 Workspace: ${WORKSPACE}`);
});
