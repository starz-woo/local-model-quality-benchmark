import os
from pathlib import Path

STRUCTURE = {
    "agent": {
        "__init__.py": "",
        "prompt.py": '''SYSTEM_PROMPT = """You are an elite CLI coding agent with a Persistent Local Wiki.
CRITICAL RULES:
1. NEVER output raw markdown code blocks (```) directly. Use <edit> to write code.
2. Before using any tool, you MUST briefly analyze the task inside <thought>...</thought> tags.
3. You have access to a local knowledge base in the `.agent_wiki/` directory. When you learn project rules, user preferences, or architecture, update or create wiki files using <edit>.
4. Skip pleasantries. Output ONLY ONE tool call per turn using exact XML tags below.

[Example Turn]
<thought>I need to check project structure and wiki index.</thought>
<read>.agent_wiki/index.md</read>

[Tools]
1. Read file: <read>filepath</read>
2. Create/Edit file:
<edit file="filepath">
<<<<<<< SEARCH
exact lines to find (leave empty for new file)
=======
replacement lines
>>>>>>> REPLACE
</edit>
3. Run shell: <bash>command</bash>
4. Grep code: <grep>keyword</grep>
5. Find files: <glob>pattern</glob>
6. Fetch web: <fetch>url</fetch>
7. Web search: <search>query</search>
8. Lint file: <lint>filepath</lint>
9. Final answer: Reply without XML tags, summarize in concise Korean."""
''',
        "client.py": '''from openai import OpenAI

class LLMClient:
    def __init__(self, model: str = "glm-5.3-flash", base_url: str = "http://localhost:11434/v1"):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key="local-key")

    def stream_chat(self, messages: list, stop_tokens: list, on_chunk):
        reply = ""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
            max_tokens=2048,
            stop=stop_tokens,
            stream=True,
            extra_body={"cache_prompt": True, "reasoning_effort": "high", "clear_thinking": True},
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                reply += delta
                on_chunk(delta)

        return reply
''',
        "engine.py": '''import re
from pathlib import Path
from .client import LLMClient
from .prompt import SYSTEM_PROMPT
from tools.base import tool_registry
from ui.display import DisplayManager, console
from rich.syntax import Syntax

class AgentEngine:
    def __init__(self, model: str = "glm-5.3-flash"):
        self.model = model
        self.llm = LLMClient(model=model)
        self.reset_context()

    def reset_context(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def clean_code_fences(self, code: str) -> str:
        code = re.sub(r"^```[a-zA-Z]*\\n?", "", code.strip())
        return re.sub(r"\\n?```$", "", code).strip()

    def handle_edit(self, filepath: str, raw_body: str) -> str:
        filepath = filepath.strip()
        path = Path(filepath)
        search_block, replace_block = "", raw_body

        if "=======" in raw_body:
            s_part, r_part = raw_body.split("=======", 1)
            search_block = self.clean_code_fences(re.sub(r"^.*?<<<<<<< SEARCH\\s*", "", s_part, flags=re.DOTALL))
            replace_block = self.clean_code_fences(re.sub(r"\\s*>>>>>>> REPLACE.*$", "", r_part, flags=re.DOTALL))
        else:
            replace_block = self.clean_code_fences(raw_body)

        is_new = not path.exists() or not search_block

        if is_new:
            preview = Syntax(replace_block, path.suffix.lstrip(".") or "python", theme="monokai", line_numbers=True, word_wrap=True)
            title = f"[bold green]✨ Create File: {filepath}[/bold green]"
        else:
            preview = DisplayManager.generate_diff(search_block, replace_block, filepath)
            title = f"[bold yellow]🔧 Patch File: {filepath}[/bold yellow]"

        if not DisplayManager.prompt_user_confirmation(title, preview):
            return f"Error: User rejected changes to {filepath}."

        try:
            if is_new:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(replace_block + "\\n", encoding="utf-8")
                console.print(f"  [bold green]✓ Created {filepath}[/bold green]\\n")
                return f"Success: Created {filepath}."

            content = path.read_text(encoding="utf-8")
            if search_block not in content:
                return f"Error: SEARCH block not found in {filepath}."

            path.write_text(content.replace(search_block, replace_block, 1) + "\\n", encoding="utf-8")
            console.print(f"  [bold green]✓ Updated {filepath}[/bold green]\\n")
            return f"Success: Updated {filepath}."
        except Exception as e:
            return f"Error: {e}"

    def parse_and_execute(self, text: str) -> str | None:
        for tag in ["read", "bash", "grep", "glob", "fetch", "search", "lint"]:
            if m := re.search(f"<{tag}>(.*?)</{tag}>", text, re.DOTALL):
                console.print(f"  [dim]⚡ Executing [{tag}]...[/dim]")
                func = tool_registry.get(tag)
                return f"Obs:\\n" + func(m.group(1))

        if m := re.search(r'<edit.*?file=["\']([^"\']+)["\'].*?>(.*?)</edit>', text, re.DOTALL):
            return "Obs: " + self.handle_edit(m.group(1), m.group(2))

        if md_m := re.search(r"```[a-zA-Z]*\\n(.*?)```", text, re.DOTALL):
            fp = console.input("  [cyan]💡 Detected code block. Save as filename: [/cyan]").strip()
            if fp:
                return "Obs: " + self.handle_edit(fp, md_m.group(1))

        return None

    def run_turn(self, user_input: str, max_steps: int = 10):
        self.messages.append({"role": "user", "content": user_input})
        stop_tokens = [f"</{t}>" for t in ["read", "edit", "bash", "grep", "glob", "fetch", "search", "lint"]]

        for _ in range(max_steps):
            console.print("[bold cyan]🤖 Assistant:[/bold cyan] ", end="")
            
            def stream_callback(delta):
                console.print(delta, end="")

            reply = self.llm.stream_chat(self.messages, stop_tokens, stream_callback)
            console.print("\\n")

            for tag in ["read", "edit", "bash", "grep", "glob", "fetch", "search", "lint"]:
                if f"<{tag}" in reply and f"</{tag}>" not in reply:
                    reply += f"\\n</{tag}>"

            self.messages.append({"role": "assistant", "content": reply})

            obs = self.parse_and_execute(reply)
            if obs is None:
                break
            self.messages.append({"role": "user", "content": obs})
'''
    },
    "tools": {
        "__init__.py": "",
        "base.py": '''class ToolRegistry:
    def __init__(self):
        self.registry = {}

    def register(self, name: str, func):
        self.registry[name] = func

    def get(self, name: str):
        return self.registry.get(name)

tool_registry = ToolRegistry()
''',
        "file_tools.py": '''import subprocess
from pathlib import Path
from .base import tool_registry

@tool_registry.register("read")
def tool_read(filepath: str) -> str:
    path = Path(filepath.strip())
    if not path.exists():
        return f"Error: {filepath} not found."
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        if len(lines) > 300:
            return "\\n".join(lines[:150]) + "\\n...(truncated)...\\n" + "\\n".join(lines[-150:])
        return content
    except Exception as e:
        return f"Error: {e}"

@tool_registry.register("glob")
def tool_glob(pattern: str) -> str:
    files = [str(p) for p in Path.cwd().glob(pattern.strip()) if not any(part.startswith(".") for part in p.parts)]
    return "\\n".join(files) if files else "No files matched."

@tool_registry.register("lint")
def tool_lint(filepath: str) -> str:
    try:
        import sys
        res = subprocess.run([sys.executable, "-m", "py_compile", filepath.strip()], capture_output=True, text=True)
        return "Success: Clean." if res.returncode == 0 else f"Lint Error:\\n{res.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"
''',
        "search_tools.py": '''import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from duckduckgo_search import DDGS
from .base import tool_registry

class HTMLFilter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, data):
        self.text.append(data)

@tool_registry.register("grep")
def tool_grep(keyword: str) -> str:
    keyword = keyword.strip()
    matches = []
    for p in Path.cwd().rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.parts) and p.suffix in [".py", ".md", ".txt", ".json", ".js"]:
            try:
                for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if keyword in line:
                        matches.append(f"{p}:{idx}: {line.strip()}")
            except Exception:
                continue
    return "\\n".join(matches[:25]) if matches else f"No matches for '{keyword}'."

@tool_registry.register("fetch")
def tool_fetch(url: str) -> str:
    try:
        req = urllib.request.Request(url.strip(), headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as res:
            parser = HTMLFilter()
            parser.feed(res.read().decode('utf-8', errors='ignore'))
            text = re.sub(r'\\s+', ' ', " ".join(parser.text)).strip()
            return text[:1500]
    except Exception as e:
        return f"Error: {e}"

@tool_registry.register("search")
def tool_search(query: str) -> str:
    try:
        results = DDGS().text(query.strip(), max_results=3)
        return "\\n".join([f"- {r.get('title')}: {r.get('body', '')[:150]}" for r in results]) if results else "No results."
    except Exception as e:
        return f"Error: {e}"
''',
        "sys_tools.py": '''import subprocess
from .base import tool_registry

@tool_registry.register("bash")
def tool_bash(cmd: str) -> str:
    try:
        res = subprocess.run(cmd.strip(), shell=True, capture_output=True, text=True, timeout=20)
        output = (res.stdout + res.stderr).strip()
        return output if output else "Success (no output)."
    except Exception as e:
        return f"Error: {e}"
'''
    },
    "ui": {
        "__init__.py": "",
        "display.py": '''import difflib
from pathlib import Path
from rich.console import Console
from rich.syntax import Syntax
from rich.tree import Tree

console = Console()

class DisplayManager:
    @staticmethod
    def render_banner(model: str):
        console.print(f"\\n[bold bright_cyan]⚡ Claude Code CLI (Wiki-Enabled)[/bold bright_cyan] [dim]({model})[/dim]")
        console.print(f"[dim]Commands: [bold]/clear[/bold] (reset) • [bold]/tree[/bold] (files) • [bold]/wiki[/bold] (knowledge) • [bold]/exit[/bold] (quit)[/dim]\\n")

    @staticmethod
    def show_file_tree():
        tree = Tree(f"📁 [bold blue]{Path.cwd().name}[/bold blue]")
        for p in sorted(Path.cwd().iterdir()):
            if p.name.startswith(".") or p.name == "__pycache__":
                continue
            icon = "🐍 " if p.suffix == ".py" else ("📂 " if p.is_dir() else "📄 ")
            tree.add(f"{icon}{p.name}")
        console.print(tree)
        console.print()

    @staticmethod
    def show_wiki():
        wiki_dir = Path(".agent_wiki")
        if not wiki_dir.exists() or not list(wiki_dir.glob("*.md")):
            console.print("[dim]No local wiki found yet. Ask the agent to create one![/dim]\\n")
            return
        console.print("[bold cyan]📚 Local Agent Wiki Knowledge Base:[/bold cyan]")
        for p in sorted(wiki_dir.glob("*.md")):
            console.print(f"  - [green]{p.name}[/green]")
        console.print()

    @staticmethod
    def generate_diff(old_str: str, new_str: str, filename: str) -> Syntax:
        diff_lines = list(difflib.unified_diff(
            old_str.splitlines(), new_str.splitlines(),
            fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=""
        ))
        diff_text = "\\n".join(diff_lines) if diff_lines else new_str
        return Syntax(diff_text, "diff", theme="monokai", line_numbers=False, word_wrap=True)

    @staticmethod
    def prompt_user_confirmation(title: str, preview_content) -> bool:
        console.print(f"\\n  {title}")
        console.print(preview_content)
        confirm = console.input("  [bold yellow]Apply changes? (y/n): [/bold yellow]").strip().lower()
        if confirm != "y":
            console.print("  [dim red]✗ Discarded.[/dim red]")
            return False
        return True
'''
    },
    ".agent_wiki": {
        "index.md": "# Agent Local Wiki\\n\\nWelcome to your agent's persistent knowledge base.\\n- Project rules and preferences will be stored here.\\n"
    },
    "main.py": '''from agent.engine import AgentEngine
from ui.display import DisplayManager, console

if __name__ == "__main__":
    engine = AgentEngine(model="glm-5.3-flash")
    console.clear()
    DisplayManager.render_banner("glm-5.3-flash")

    while True:
        try:
            query = console.input("[bold green]❯ [/bold green]").strip()
            if not query:
                continue
            if query.lower() in ["/exit", "exit", "quit"]:
                break
            if query.lower() == "/clear":
                engine.reset_context()
                console.clear()
                DisplayManager.render_banner("glm-5.3-flash")
                console.print("[dim]✓ Memory cleared.[/dim]\\n")
                continue
            if query.lower() == "/tree":
                DisplayManager.show_file_tree()
                continue
            if query.lower() == "/wiki":
                DisplayManager.show_wiki()
                continue

            engine.run_turn(query)
            console.print()
        except KeyboardInterrupt:
            console.print("\\n[dim]Exiting...[/dim]")
            break
'''
}

def build_project():
    print("📦 Building Agent Project Structure...")
    for base, contents in STRUCTURE.items():
        if isinstance(contents, dict):
            Path(base).mkdir(parents=True, exist_ok=True)
            for filename, code in contents.items():
                file_path = Path(base) / filename
                file_path.write_text(code, encoding="utf-8")
                print(f"  Created: {file_path}")
        else:
            file_path = Path(base)
            file_path.write_text(contents, encoding="utf-8")
            print(f"  Created: {file_path}")
    print("\\n✨ Successfully built! Run 'python main.py' to start your agent.")

if __name__ == "__main__":
    build_project()
