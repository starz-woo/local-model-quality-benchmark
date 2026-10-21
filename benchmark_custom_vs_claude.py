import sys
import subprocess

# Auto-install required packages
def ensure_packages(pkg_map: dict):
    for mod_name, pip_name in pkg_map.items():
        try:
            __import__(mod_name)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pip_name])

ensure_packages({"openai": "openai", "rich": "rich"})

import os
import re
import time
import shutil
from pathlib import Path
from openai import OpenAI
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.box import ROUNDED

console = Console()

# ==========================================
# Configuration (Match both to the EXACT SAME Local Model)
# ==========================================
MODEL_NAME = "qwen2.5-coder:7b"           # Local model name
OPENAI_BASE_URL = "http://localhost:11434/v1"     # For Custom Agent
ANTHROPIC_BASE_URL = "http://localhost:11434"     # For Claude Code CLI (Ollama/LiteLLM proxy)

WORKSPACE_CUSTOM = Path("./bench_custom_ws")
WORKSPACE_CLAUDE = Path("./bench_claude_ws")

client = OpenAI(base_url=OPENAI_BASE_URL, api_key="local-key")

CUSTOM_SYS_PROMPT = """You are an elite CLI coding agent.
NEVER output raw markdown code blocks (```). You MUST use <edit> to write code.
Skip pleasantries. Output ONLY ONE tool call per turn.

[Tools]
Output no XML tags. Reply "DONE"."""

# 3 Sequential Coding Tasks (Creation -> Refactoring -> Bug Fix/Patch)
BENCHMARK_TASKS = [
    (
        "Create `solution.py` with a function `calc_fib(n)` that returns the nth Fibonacci number (0-indexed: calc_fib(0)=0, calc_fib(1)=1), and prints `calc_fib(10)`.",
        "55"
    ),
    (
        "Edit `solution.py` to add a function `calc_fact(n)` returning n factorial, and print `calc_fib(10) + calc_fact(5)` instead.",
        "175"
    ),
    (
        "In `solution.py`, change the final print statement to print `calc_fib(12) + calc_fact(5)`.",
        "264"
    ),
]


class RealClaudeVsCustomBenchmark:
    def __init__(self, model: str):
        self.model = model

    def setup_dirs(self):
        for ws in [WORKSPACE_CUSTOM, WORKSPACE_CLAUDE]:
            if ws.exists():
                shutil.rmtree(ws)
            ws.mkdir(parents=True, exist_ok=True)

    def verify_output(self, ws: Path, filename: str, expected: str) -> tuple[bool, str]:
        target = ws / filename
        if not target.exists():
            return False, "File not created"
        try:
            res = subprocess.run([sys.executable, str(target)], capture_output=True, text=True, timeout=5)
            actual = res.stdout.strip()
            if res.returncode != 0:
                return False, f"Runtime Error: {res.stderr.strip()[:50]}"
            return (actual == expected), f"Got '{actual}' (Expected '{expected}')"
        except Exception as e:
            return False, str(e)

    # ----------------------------------------------------
    # Runner A: Our Custom XML Agent (Direct Python)
    # ----------------------------------------------------
    def apply_custom_edit(self, ws: Path, filepath: str, raw_body: str) -> str:
        path = ws / Path(filepath.strip()).name
        clean = lambda s: re.sub(r"\n?```$", "", re.sub(r"^```[a-zA-Z]*\n?", "", s.strip())).strip()

        if "=======" in raw_body:
            s_part, r_part = raw_body.split("=======", 1)
            search_b = clean(re.sub(r"^.*?<<<<<<< SEARCH\s*", "", s_part, flags=re.DOTALL))
            replace_b = clean(re.sub(r"\s*>>>>>>> REPLACE.*$", "", r_part, flags=re.DOTALL))
            if path.exists() and search_b in path.read_text(encoding="utf-8"):
                new_c = path.read_text(encoding="utf-8").replace(search_b, replace_b, 1)
                path.write_text(new_c + "\n", encoding="utf-8")
                return "Success: Updated."
            # Fallback if search block slightly mismatched
            path.write_text(replace_b + "\n", encoding="utf-8")
            return "Success: Overwritten."
        else:
            path.write_text(clean(raw_body) + "\n", encoding="utf-8")
            return "Success: Created."

    def run_custom_agent(self) -> dict:
        messages = [{"role": "system", "content": CUSTOM_SYS_PROMPT}]
        stats = {"times": [], "passed": 0, "details": []}

        for idx, (prompt, expected) in enumerate(BENCHMARK_TASKS, 1):
            console.print(f"  [cyan]:arrow_forward: Custom Agent - Task {idx}/3...[/cyan]")
            t0 = time.perf_counter()
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=1024,
                stop=["</edit>"],
                extra_body={"cache_prompt": True},
            )
            reply = response.choices[0].message.content or ""
            if "<edit" in reply and "</edit>" not in reply:
                reply += "\n</edit>"

            messages.append({"role": "assistant", "content": reply})

            edit_m = re.search(r'<edit.*?file=["\']([^"\']+)["\'].*?>(.*?)</edit>', reply, re.DOTALL)
            if edit_m:
                obs = self.apply_custom_edit(WORKSPACE_CUSTOM, edit_m.group(1), edit_m.group(2))
                messages.append({"role": "user", "content": f"Obs: {obs}"})
            else:
                # Fallback if raw markdown was emitted
                md_m = re.search(r"```[a-zA-Z]*\n(.*?)```", reply, re.DOTALL)
                if md_m:
                    self.apply_custom_edit(WORKSPACE_CUSTOM, "solution.py", md_m.group(1))

            elapsed = time.perf_counter() - t0
            ok, msg = self.verify_output(WORKSPACE_CUSTOM, "solution.py", expected)
            stats["times"].append(elapsed)
            if ok:
                stats["passed"] += 1
            stats["details"].append(f"T{idx}: {elapsed:.2f}s ({':white_check_mark:' if ok else ':x: ' + msg})")

        return stats

    # ----------------------------------------------------
    # Runner B: Real `claude` CLI mapped to Local LLM
    # ----------------------------------------------------
    def run_claude_cli(self) -> dict:
        stats = {"times": [], "passed": 0, "details": []}

        # Check if `claude` binary exists in PATH
        if not shutil.which("claude"):
            console.print("  [bold red]:warning: `claude` CLI not found in PATH! Skipping CLI run.[/bold red]")
            return {"times": [0, 0, 0], "passed": 0, "details": ["CLI not installed"] * 3}

        # Environment variables mapping Claude Code to Local LLM
        env = os.environ.copy()
        env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
        env["ANTHROPIC_API_KEY"] = env.get("ANTHROPIC_API_KEY", "local-key")
        env["ANTHROPIC_MODEL"] = self.model

        for idx, (prompt, expected) in enumerate(BENCHMARK_TASKS, 1):
            console.print(f"  [yellow]:arrow_forward: Claude Code CLI - Task {idx}/3...[/yellow]")
            t0 = time.perf_counter()

            # Use -p (headless print mode), -c (continue conversation for KV cache), and skip permission prompts
            cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions", "--model", self.model]
            if idx > 1:
                cmd.insert(1, "-c")  # Continue previous session context

            try:
                subprocess.run(
                    cmd,
                    cwd=str(WORKSPACE_CLAUDE),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120  # Local LLM via Claude Code can be very slow due to huge system prompt
                )
            except subprocess.TimeoutExpired:
                stats["times"].append(120.0)
                stats["details"].append(f"T{idx}: Timeout (>120s) :x:")
                continue

            elapsed = time.perf_counter() - t0
            ok, msg = self.verify_output(WORKSPACE_CLAUDE, "solution.py", expected)
            stats["times"].append(elapsed)
            if ok:
                stats["passed"] += 1
            stats["details"].append(f"T{idx}: {elapsed:.2f}s ({':white_check_mark:' if ok else ':x: ' + msg})")

        return stats


if __name__ == "__main__":
    console.print(Panel(
        f"[bold cyan]:zap: Head-to-Head Benchmark: Custom Agent vs. Claude Code CLI[/bold cyan]\n"
        f"[dim]Both powered by the exact same local LLM: [bold white]{MODEL_NAME}[/bold white][/dim]",
        box=ROUNDED, border_style="cyan"
    ))

    bench = RealClaudeVsCustomBenchmark(model=MODEL_NAME)
    bench.setup_dirs()

    console.print("\n[bold green]1. Running Custom Python XML Agent...[/bold green]")
    custom_stats = bench.run_custom_agent()

    console.print("\n[bold yellow]2. Running Official `claude` CLI (mapped to Local LLM)...[/bold yellow]")
    claude_stats = bench.run_claude_cli()

    # Build Comparison Report
    c_total = sum(custom_stats["times"])
    cl_total = sum(claude_stats["times"])
    speed_ratio = (cl_total / c_total) if c_total > 0 and cl_total > 0 else 0

    table = Table(title=f"\n:trophy: Final Benchmark Report ({MODEL_NAME})", box=ROUNDED, show_lines=True)
    table.add_column("Metric", style="bold white")
    table.add_column("Custom XML Agent\n(Lightweight + Diff)", justify="right", style="bold green")
    table.add_column("Claude Code CLI\n(Mapped to Local LLM)", justify="right", style="bold yellow")
    table.add_column("Winner / Gap", justify="right", style="bold cyan")

    for i in range(3):
        t_c = custom_stats["times"][i]
        t_cl = claude_stats["times"][i]
        diff_str = f"Custom is {t_cl / t_c:.1f}x faster" if (t_c > 0 and t_cl > 0) else "-"
        table.add_row(
            f"Task {i+1} Latency",
            custom_stats["details"][i],
            claude_stats["details"][i],
            diff_str
        )

    table.add_row(
        "Total Time (All 3 Tasks)",
        f"{c_total:.2f} s",
        f"{cl_total:.2f} s",
        f":fire: {speed_ratio:.1f}x Faster" if speed_ratio > 0 else "N/A"
    )
    table.add_row(
        "Code Quality (Pass Rate)",
        f"{custom_stats['passed']} / 3 ({custom_stats['passed']/3*100:.0f}%)",
        f"{claude_stats['passed']} / 3 ({claude_stats['passed']/3*100:.0f}%)",
        "Custom Wins" if custom_stats["passed"] >= claude_stats["passed"] else "Claude CLI Wins"
    )

    console.print(table)
