import os
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("⚠️ WARNING: GROQ_API_KEY not set. The agent will fail on API calls.")
    GROQ_API_KEY = ""  # placeholder to avoid crash
import json
import subprocess
import shutil
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)  # allows your frontend to call it (if separate)

# ---------- CONFIG ----------

client = Groq(api_key=GROQ_API_KEY)
WORKSPACE = "/tmp/agent_workspace"
os.makedirs(WORKSPACE, exist_ok=True)

ALLOW_DELETE = False   # Keep this False for safety
ALLOW_RUN = False      # Keep this False for safety
MAX_ITERATIONS = 10

# ---------- TOOLS ----------
def write_file(path, content):
    full = os.path.join(WORKSPACE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Wrote {path} ({len(content)} chars)"

def read_file(path):
    full = os.path.join(WORKSPACE, path)
    try:
        with open(full, 'r', encoding='utf-8') as f:
            return f.read()[:2000]
    except FileNotFoundError:
        return f"File {path} not found"

def delete_file(path):
    if not ALLOW_DELETE:
        return "Deletion disabled"
    full = os.path.join(WORKSPACE, path)
    if os.path.isdir(full):
        shutil.rmtree(full)
    else:
        os.remove(full)
    return f"Deleted {path}"

def list_files(path="."):
    full = os.path.join(WORKSPACE, path)
    try:
        items = os.listdir(full)
        return "\n".join(items)
    except:
        return "Folder not found"

def run_command(cmd):
    if not ALLOW_RUN:
        return "Command execution disabled"
    result = subprocess.run(cmd, shell=True, cwd=WORKSPACE,
                            capture_output=True, text=True, timeout=60)
    out = result.stdout[:2000]
    err = result.stderr[:500]
    return f"OUT: {out}\nERR: {err}" if err else f"OUT: {out}"

TOOLS = {
    "write_file": write_file,
    "read_file": read_file,
    "delete_file": delete_file,
    "list_files": list_files,
    "run_command": run_command,
}

# ---------- AGENT LOOP ----------
def agent_loop(prompt):
    messages = [
        {"role": "system", "content": f"""
You are an autonomous developer. Workspace: {WORKSPACE}
Tools: write_file, read_file, delete_file, list_files, run_command.
Output JSON: {{"tool":"write_file","path":"x","content":"y"}} or {{"done":"message"}}
"""},
        {"role": "user", "content": prompt}
    ]
    for i in range(MAX_ITERATIONS):
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        try:
            action = json.loads(resp.choices[0].message.content)
        except:
            yield {"error": "Invalid JSON"}
            break

        if "done" in action:
            yield {"done": action["done"]}
            break

        tool = action.get("tool")
        if tool not in TOOLS:
            yield {"error": f"Unknown tool: {tool}"}
            break

        try:
            if tool == "write_file":
                result = TOOLS[tool](action["path"], action["content"])
            elif tool == "run_command":
                result = TOOLS[tool](action["cmd"])
            else:
                result = TOOLS[tool](action.get("path", "."))
        except Exception as e:
            result = f"Error: {e}"

        yield {"step": i+1, "action": action, "result": result}
        messages.append({"role": "assistant", "content": json.dumps(action)})
        messages.append({"role": "user", "content": f"Result: {result}"})

# ---------- API ENDPOINT ----------
@app.route('/agent', methods=['POST'])
def agent_endpoint():
    data = request.json
    prompt = data.get('prompt', '')
    if not prompt:
        return jsonify({"error": "No prompt"}), 400

    results = []
    for chunk in agent_loop(prompt):
        results.append(chunk)
    return jsonify(results)

# ---------- FRONTEND (HTML) ----------
HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🤖 Real Agent</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { background:#0d1117; color:#e6edf3; font-family:system-ui, sans-serif; padding:16px; max-width:700px; margin:auto; }
    h1 { font-size:1.5rem; border-bottom:1px solid #30363d; padding-bottom:10px; margin-bottom:16px; }
    #chat { background:#161b22; border-radius:8px; padding:12px; height:450px; overflow-y:auto; margin-bottom:12px; border:1px solid #30363d; }
    .msg { background:#0d1117; padding:10px 14px; border-radius:8px; margin-bottom:8px; border-left:3px solid #58a6ff; white-space:pre-wrap; word-break:break-word; }
    .msg.assistant { border-left-color:#f0883e; }
    .msg.user { border-left-color:#58a6ff; }
    .input-row { display:flex; gap:10px; }
    .input-row textarea { flex:1; background:#0d1117; border:1px solid #30363d; color:#e6edf3; padding:10px; border-radius:8px; font-family:inherit; min-height:60px; resize:vertical; }
    .input-row button { background:#1f6feb; border:none; color:#fff; padding:0 24px; border-radius:8px; font-weight:bold; cursor:pointer; }
    #status { color:#8b949e; text-align:center; margin-top:8px; }
  </style>
</head>
<body>
  <h1>🧠 Real Agent (Server)</h1>
  <div id="chat"><div class="msg assistant">👋 I write real files on the server. Try: <em>"Build a Python Flask hello world"</em></div></div>
  <div class="input-row">
    <textarea id="prompt" placeholder="Describe your app..."></textarea>
    <button id="sendBtn">Send</button>
  </div>
  <div id="status">✅ Ready</div>

  <script>
    const chatEl = document.getElementById('chat');
    const promptEl = document.getElementById('prompt');
    const sendBtn = document.getElementById('sendBtn');
    const statusEl = document.getElementById('status');

    function addMsg(text, cls='assistant') {
      const div = document.createElement('div');
      div.className = `msg ${cls}`;
      div.textContent = text;
      chatEl.appendChild(div);
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    sendBtn.addEventListener('click', async () => {
      const prompt = promptEl.value.trim();
      if (!prompt) return;
      promptEl.value = '';
      addMsg('You: ' + prompt, 'user');
      addMsg('⏳ Agent thinking...');
      statusEl.textContent = '⏳ Running...';

      try {
        const res = await fetch('/agent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt })
        });
        const data = await res.json();
        chatEl.removeChild(chatEl.lastChild);
        if (data.error) {
          addMsg('❌ ' + data.error);
        } else {
          data.forEach(item => {
            if (item.done) addMsg('🎉 Done: ' + item.done);
            else if (item.error) addMsg('❌ ' + item.error);
            else if (item.step) {
              const action = JSON.stringify(item.action);
              addMsg(`Step ${item.step}: ${action}\n→ ${item.result}`);
            }
          });
        }
        statusEl.textContent = '✅ Done';
      } catch (e) {
        chatEl.removeChild(chatEl.lastChild);
        addMsg('❌ Network error: ' + e.message);
        statusEl.textContent = '❌ Error';
      }
    });
  </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
