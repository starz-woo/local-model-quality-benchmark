import sys
import subprocess

# Auto-install required packages in the current pyenv environment
def ensure_packages(pkg_map: dict):
    for mod_name, pip_name in pkg_map.items():
        try:
            __import__(mod_name)
        except ImportError:
            print(f"📦 Installing {pip_name}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pip_name])

ensure_packages({
    "openai": "openai",
    "rich": "rich",
    "duckduckgo_search": "duckduckgo-search",
})

import re
import difflib
from pathlib import Path
from openai import OpenAI
from duckduckgo_search import DDGS
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.tree import Tree
from rich. box import ROUNDED

console = Console()

# 1. Local LLM Endpoint Configuration (Ollama, vLLM, llama.cpp)
MODEL_NAME = "qwen2.5-coder:7b"  # Change to your local model name
BASE_URL = "http://localhost:11434/v1"

client = OpenAI(base_url=BASE_URL, api_key="local-key")

# 2. Ultra-compact English System Prompt (Maximizes KV Cache & Token Efficiency)
SYSTEM_PROMPT = """You are an elite CLI coding agent.
CRITICAL RULE: NEVER output raw markdown code blocks (```) to the user. To create or edit files, you MUST use the <edit> XML tag.
Skip pleasantries. Output ONLY ONE tool call per turn.

[Tools]
1. Read file:
<read>filepath</read>

2. Create NEW file:
<edit file="filepath">
full file code here
</edit>

3. Edit EXISTING file (Include ONLY changed lines):
<edit file="filepath">
<<<<<<< SEARCH
exact lines to find
=======
replacement lines
>>>>>>> REPLACE
</edit>

4. Run shell command:
<bash>command</bash>

5. Web search:
<search>query</search>

6. Final answer (ONLY AFTER all tasks are done):
Output no XML tags. Summarize results in concise Korean."""


class LocalClaudeCode:
    def __init__(self, model: str):
        self.model = model
        self. reset_context()

    def reset_context(self):
        # Keep system prompt static at index 0 for Prefix KV Caching
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def render_banner(self):
        banner_text = Text.from_markup(
            f"[bold cyan]⚡ LOCAL CLAUDE CODE[/bold cyan] [dim]|[/dim] "
            f"[green]Model:[/green] {self.model} [dim]|[/dim] "
            f"[yellow]KV Cache:[/yellow] Active\n"
            f"[dim]Commands: [bold]/clear[/bold] (reset memory) • [bold]/tree[/bold] (view files) • [bold]/exit[/bold] (quit)[/dim]"
        )
        console.print(Panel(banner_text, box=ROUNDED, border_style="bright_blue", expand=False))

    def show_file_tree(self):
        tree = Tree(f"📁 [bold blue]{Path.cwd().name}[/bold blue]")
        for p in sorted(Path.cwd().iterdir()):
            if p.name.startswith(".") or p.name == "__pycache__":
                continue
            icon = "🐍 " if p.suffix == ".py" else ("📂 " if p.is_dir() else "📄 ")
            tree.add(f"{icon}{p.name}")
        console.print(Panel(tree, title="[bold]Workspace[/bold]", box=ROUNDED, border_style="dim"))

    def clean_code_fences(self, code: str) -> str:
        code = re.sub(r"^```[a-zA-Z]*\n?", "", code.strip())
        return re.sub(r"\n?```$", "", code).strip()

    def generate_diff_view(self, old_str: str, new_str: str, filename: str) -> Syntax:
        diff_lines = list(difflib.unified_diff(
            old_str.splitlines(),
            new_str.splitlines(),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm=""
        ))
        diff_text = "\n".join(diff_lines) if diff_lines else new_str
        return Syntax(diff_text, "diff", theme="monokai", line_numbers=False, word_wrap=True)

    def tool_read(self, filepath: str) -> str:
        path = Path(filepath.strip())
        if not path.exists():
            return f"Error: {filepath} not found."
        try:
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            if len(lines) > 300:
                return "\n".join(lines[:150]) + "\n...(truncated)...\n" + "\n".join(lines[-150:])
            return content
        except Exception as e:
            return f"Error: {e}"

    def tool_edit(self, filepath: str, raw_body: str) -> str:
        filepath = filepath.strip()
        path = Path(filepath)
        search_block = ""
        replace_block = raw_body

        # Automatically split SEARCH/REPLACE markers if present
        if "=======" in raw_body:
            s_part, r_part = raw_body.split("=======", 1)
            search_block = self.clean_code_fences(re.sub(r"^.*?<<<<<<< SEARCH\s*", "", s_part, flags=re.DOTALL))
            replace_block = self.clean_code_fences(re.sub(r"\s*>>>>>>> REPLACE.*$", "", r_part, flags=re.DOTALL))
        else:
            replace_block = self.clean_code_fences(raw_body)

        is_new = not path.exists() or not search_block

        # Render Trendy Preview Panel (Syntax for new file, Unified Diff for edits)
        if is_new:
            ext = path.suffix.lstrip(".") or "python"
            preview = Syntax(replace_block, ext, theme="monokai", line_numbers=True, word_wrap=True)
            title = f"[bold green]✨ Create File: {filepath}[/bold green]"
            b_style = "green"
        else:
            preview = self.generate_diff_view(search_block, replace_block, filepath)
            title = f"[bold yellow]🔧 Patch File: {filepath}[/bold yellow]"
            b_style = "yellow"

        console.print(Panel(preview, title=title, box=ROUNDED, border_style=b_style))

        confirm = console.input(f"  [bold yellow]╰─▶ Apply changes to `{filepath}`? (y/n): [/bold yellow]").strip().lower()
        if confirm != "y":
            console.print("  [dim red]✗ Changes discarded by user.[/dim red]")
            return f"Error: User rejected changes to {filepath}."

        try:
            if is_new:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(replace_block + "\n", encoding="utf-8")
                console.print(f"  [bold green]✓ Saved {filepath}[/bold green]")
                return f"Success: Created {filepath}."

            content = path.read_text(encoding="utf-8")
            if search_block not in content:
                console.print("  [bold red]✗ Error: Exact SEARCH lines not found in file.[/bold red]")
                return f"Error: SEARCH block not found in {filepath}. Read the file first."

            new_content = content.replace(search_block, replace_block, 1)
            path.write_text(new_content, encoding="utf-8")
            console.print(f"  [bold green]✓ Patched {filepath}[/bold green]")
            return f"Success: Updated {filepath}."
        except Exception as e:
            return f"Error: {e}"

    def tool_bash(self, cmd: str) -> str:
        cmd = cmd.strip()
        console.print(Panel(Syntax(cmd, "bash", theme="monokai"), title="[bold magenta]🐚 Shell Command[/bold magenta]", box=ROUNDED, border_style="magenta"))
        confirm = console.input("  [bold magenta]╰─▶ Execute command? (y/n): [/bold magenta]").strip().lower()
        if confirm != "y":
            console.print("  [dim red]✗ Command aborted.[/dim red]")
            return "Error: Command aborted by user."

        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
            output = (res.stdout + res.stderr).strip()
            if len(output) > 1000:
                output = "...(truncated)...\n" + output[-1000:]
            if output:
                console.print(Panel(Text(output, style="dim"), title="Output", box=ROUNDED, border_style="dim"))
            else:
                console.print("  [bold green]✓ Executed (no output)[/bold green]")
            return output if output else "Success (no output)."
        except subprocess.TimeoutExpired:
            return "Error: Command timed out (20s)."

    def tool_search(self, query: str) -> str:
        query = query.strip()
        console.print(f"  [bold cyan]🌐 Searching web:[/bold cyan] [italic]{query}[/italic]")
        try:
            results = DDGS().text(query, max_results=3)
            if not results:
                return "No results found."
            compact = [f"- {r.get('title')}: {r.get('body', '')[:200]} ({r.get('href')})" for r in results]
            return "\n".join(compact)
        except Exception as e:
            return f"Error: {e}"

    def parse_and_execute(self, response_text: str) -> str | None:
        # 1. <read>
        read_m = re.search(r"<read>(.*?)</read>", response_text, re.DOTALL)
        if read_m:
            fp = read_m.group(1).strip()
            console.print(f"  [bold cyan]📖 Reading:[/bold cyan] {fp}")
            return f"Obs ({fp}):\n" + self.tool_read(fp)

        # 2. <edit> (Handles both new files and SEARCH/REPLACE diffs)
        edit_m = re.search(r'<edit.*?file=["\']([^"\']+)["\'].*?>(.*?)</edit>', response_text, re.DOTALL)
        if edit_m:
            fp, body = edit_m.groups()
            return "Obs: " + self.tool_edit(fp, body)

        # 3. <bash>
        bash_m = re.search(r"<bash>(.*?)</bash>", response_text, re.DOTALL)
        if bash_m:
            return "Obs:\n" + self.tool_bash(bash_m.group(1))

        # 4. <search>
        search_m = re.search(r"<search>(.*?)</search>", response_text, re.DOTALL)
        if search_m:
            return "Obs:\n" + self.tool_search(search_m.group(1))

        # 5. Smart Fallback: If model accidentally outputs ```python without <edit>
        md_m = re.search(r"```[a-zA-Z]*\n(.*?)```", response_text, re.DOTALL)
        if md_m:
            fp = console.input("  [bold cyan]╰─▶ 💡 Detected code block. Enter filename to save (or Enter to skip): [/bold cyan]").strip()
            if fp:
                return "Obs: " + self.tool_edit(fp, md_m.group(1))

        return None

    def stream_response(self) -> str:
        reply = ""
        with Live(
            Panel(Text("Thinking...", style="italic dim"), title="[bold bright_blue]🤖 Agent[/bold bright_blue]", box=ROUNDED, border_style="bright_blue"),
            console=console,
            refresh_per_second=15,
        ) as live:
            stream = client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                temperature=0.0,
                max_tokens=1024,
                stop=["</read>", "</edit>", "</bash>", "</search>"],
                stream=True,
                extra_body={"cache_prompt": True},
            )

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    reply += delta
                    live.update(
                        Panel(Text(reply), title="[bold bright_blue]🤖 Agent (Streaming...)[/bold bright_blue]", box=ROUNDED, border_style="bright_blue")
                    )

            # Restore closing tags stripped by stop tokens
            for tag in ["read", "edit", "bash", "search"]:
                if f"<{tag}" in reply and f"</{tag}>" not in reply:
                    reply += f"\n</{tag}>"

            live.update(
                Panel(Text(reply.strip()), title="[bold bright_blue]🤖 Agent[/bold bright_blue]", box=ROUNDED, border_style="bright_blue")
            )

        return reply

    def chat_loop(self, user_input: str, max_steps: int = 10):
        self.messages.append({"role": "user", "content": user_input})

        for step in range(1, max_steps + 1):
            reply = self.stream_response()
            self.messages.append({"role": "assistant", "content": reply})

            observation = self.parse_and_execute(reply)
            if observation is None:
                break
            self.messages.append({"role": "user", "content": observation})
        else:
            console.print("  [bold red]⚠ Max steps (10) reached.[/bold red]")


if __name__ == "__main__":
    agent = LocalClaudeCode(model=MODEL_NAME)
    console.clear()
    agent.render_banner()

    while True:
        try:
            ctx_len = len(agent.messages)
            prompt_label = f"\n[bold bright_green]You[/bold bright_green] [dim](msgs:{ctx_len})[/dim] [bold bright_green]❯ [/bold bright_green]"
            query = console.input(prompt_label).strip()

            if not query:
                continue
            if query.lower() in ["/exit", "exit", "quit"]:
                console.print("[dim]Bye! 👋[/dim]")
                break
            if query.lower() == "/clear":
                agent.reset_context()
                console.clear()
                agent.render_banner()
                console.print("  [bold green]✓ Memory cleared.[/bold green]")
                continue
            if query.lower() == "/tree":
                agent.show_file_tree()
                continue

            agent.chat_loop(query)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted. Type /exit to quit.[/dim]")
