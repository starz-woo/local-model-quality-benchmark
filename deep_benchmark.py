import sys
import subprocess
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

MODEL_NAME = "qwen2.5-coder:7b"  # Change to your local model name
BASE_URL = "http://localhost:11434/v1"
client = OpenAI(base_url=BASE_URL, api_key="local-key")

WORKSPACE = Path("./deep_bench_workspace")

# ==========================================
# 1. Custom XML Agent Prompt (Token Efficient)
# ==========================================
CUSTOM_SYS_PROMPT = """You are an elite CLI coding agent.
To create or edit files, you MUST use the <edit file="filename"> XML tag.
When finished and all tests pass, output "DONE".
[Tools]
<edit file="filepath">
code here
</edit>"""

# ==========================================
# 2. Standard Baseline Agent Prompt (Verbose Rewrite)
# ==========================================
STANDARD_SYS_PROMPT = """You are a coding assistant. To write a file, output its full code inside a markdown code block ```python ... ```.
When finished, output "DONE"."""


class DeepBenchmarkRunner:
    def __init__(self, model: str):
        self.model = model

    def reset_workspace(self, sub_dir: str):
        ws = WORKSPACE / sub_dir
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def call_llm(self, messages: list) -> tuple[str, float]:
        start_t = time.perf_counter()
        reply = ""
        stream = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
            max_tokens=1500,
            stream=True,
            extra_body={"cache_prompt": True},
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                reply += delta
        return reply, (time.perf_counter() - start_t)

    def extract_and_save_code(self, ws: Path, reply: str, is_custom: bool) -> tuple[bool, str]:
        code_blocks = []
        if is_custom:
            matches = re.findall(r'<edit.*?file=["\']([^"\']+)["\'].*?>(.*?)</edit>', reply, re.DOTALL)
            if matches:
                for fp, content in matches:
                    clean_content = re.sub(r"\n?```$", "", re.sub(r"^```[a-zA-Z]*\n?", "", content.strip())).strip()
                    (ws / fp.strip()).write_text(clean_content + "\n", encoding="utf-8")
                    code_blocks.append(fp)
            else:
                md_matches = re.findall(r"```[a-zA-Z]*\n(.*?)```", reply, re.DOTALL)
                if md_matches:
                    (ws / "math_utils.py").write_text(md_matches[0].strip() + "\n", encoding="utf-8")
                    code_blocks.append("math_utils.py")
        else:
            md_matches = re.findall(r"```[a-zA-Z]*\n(.*?)```", reply, re.DOTALL)
            if md_matches:
                (ws / "math_utils.py").write_text(md_matches[0].strip() + "\n", encoding="utf-8")
                code_blocks.append("math_utils.py")

        return len(code_blocks) > 0, f"Saved files: {code_blocks}" if code_blocks else "No code blocks found"

    def run_unit_tests(self, ws: Path) -> tuple[bool, str]:
        try:
            res = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(ws), "-p", "test_*.py"],
                capture_output=True,
                text=True,
                timeout=10
            )
            passed = (res.returncode == 0)
            output = (res.stderr + res.stdout).strip()
            return passed, output[-300:] if output else "Tests executed (no output)"
        except Exception as e:
            return False, str(e)

    def run_agent_workflow(self, mode: str) -> dict:
        is_custom = (mode == "custom")
        sys_prompt = CUSTOM_SYS_PROMPT if is_custom else STANDARD_SYS_PROMPT
        
        tasks = [
            (
                "Create a module `math_utils.py` containing a function `is_prime(n: int) -> bool`. "
                "Also create a unit test file `test_math.py` using `unittest` with at least 3 test cases.",
                "test_math.py"
            ),
            (
                "Edit `math_utils.py` to add a second function `nth_prime(n: int) -> int` that returns the n-th prime number (1-indexed). "
                "Update `test_math.py` to also test `nth_prime`.",
                "test_math.py"
            ),
            (
                "Ensure `nth_prime` and `is_prime` handle edge cases properly (e.g., n <= 0 or non-integers raising ValueError). "
                "Make sure all unit tests pass completely.",
                "test_math.py"
            ),
        ]

        metrics = {"total_time": 0.0, "passed_tasks": 0, "total_chars": 0, "steps_taken": 0}
        ws = self.reset_workspace(mode)

        messages = [{"role": "system", "content": sys_prompt}]

        for idx, (prompt, test_file) in enumerate(tasks, 1):
            console.print(f"  [dim]:arrow_forward: [{mode.upper()}] Task {idx}/3 executing...[/dim]")
            messages.append({"role": "user", "content": prompt})

            task_success = False
            for step in range(1, 4):
                metrics["steps_taken"] += 1
                reply, elapsed = self.call_llm(messages)
                metrics["total_time"] += elapsed
                metrics["total_chars"] += len(reply)

                messages.append({"role": "assistant", "content": reply})
                self.extract_and_save_code(ws, reply, is_custom)

                passed, test_output = self.run_unit_tests(ws)
                if passed:
                    task_success = True
                    messages.append({"role": "user", "content": "Obs: All unit tests passed successfully! Proceed to next task."})
                    break
                else:
                    messages.append({"role": "user", "content": f"Obs: Unit tests failed with error:\n{test_output}\nFix the code."})

            if task_success:
                metrics["passed_tasks"] += 1

        return metrics


if __name__ == "__main__":
    console.print(Panel("[bold cyan]:fire: Deep Coding Agent Benchmark (Unit-Test Driven)[/bold cyan]\n"
                        "[dim]Testing multi-turn capability, self-correction, and unit test pass rates.[/dim]",
                        box=ROUNDED, border_style="cyan"))

    runner = DeepBenchmarkRunner(model=MODEL_NAME)

    console.print("\n[bold green]1. Running Custom XML / Token-Optimized Agent...[/bold green]")
    custom_res = runner.run_agent_workflow("custom")

    console.print("\n[bold yellow]2. Running Standard / Verbose Baseline Agent...[/bold yellow]")
    std_res = runner.run_agent_workflow("standard")

    table = Table(title=f"\n:bar_chart: Deep Benchmark Report ({MODEL_NAME})", box=ROUNDED, show_lines=True)
    table.add_column("Evaluation Metric", style="bold white")
    table.add_column("Custom XML Agent", justify="right", style="bold green")
    table.add_column("Standard Agent", justify="right", style="yellow")
    table.add_column("Comparison", justify="right", style="bold cyan")

    table.add_row(
        "Total Execution Time",
        f"{custom_res['total_time']:.2f} s",
        f"{std_res['total_time']:.2f} s",
        f"{((std_res['total_time'] - custom_res['total_time']) / std_res['total_time'] * 100):+.1f}% time"
    )
    table.add_row(
        "Total Characters Generated",
        f"{custom_res['total_chars']} chars",
        f"{std_res['total_chars']} chars",
        f"{((std_res['total_chars'] - custom_res['total_chars']) / std_res['total_chars'] * 100):+.1f}% volume"
    )
    table.add_row(
        "Unit Test Pass Rate (3 Complex Tasks)",
        f"{custom_res['passed_tasks']} / 3 passed",
        f"{std_res['passed_tasks']} / 3 passed",
        f"{(custom_res['passed_tasks']/3*100):.0f}% vs {(std_res['passed_tasks']/3*100):.0f}%"
    )
    table.add_row(
        "Total Turns / Steps Used",
        f"{custom_res['steps_taken']} steps",
        f"{std_res['steps_taken']} steps",
        "Efficiency metric"
    )

    console.print(table)
