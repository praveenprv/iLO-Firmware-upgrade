"""
Terminal UI and Console presentation layer.
Provides modern, rich interactive tables, progress bars, and prompts using the 'rich' library,
with a graceful fallback to standard ANSI terminal formatting.
"""

import sys
import time
from typing import List, Dict, Any, Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
    from rich.prompt import Prompt, Confirm
    from rich import print as rprint
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


def print_banner():
    """Display the application banner."""
    title = "HPE iLO FIRMWARE UPGRADE AUTOMATION SUITE"
    subtitle = "Redfish RESTful API | iLO 4, iLO 5, iLO 6, iLO 7"
    if RICH_AVAILABLE:
        console.print(Panel(
            f"[bold cyan]{title}[/bold cyan]\n[dim]{subtitle}[/dim]",
            border_style="bright_blue",
            expand=False,
            padding=(1, 4)
        ))
    else:
        print("=" * 60)
        print(f"  {title}")
        print(f"  {subtitle}")
        print("=" * 60)


def print_step(step_num: int, title: str):
    """Print a prominent step header."""
    if RICH_AVAILABLE:
        console.print(f"\n[bold yellow]─── Step {step_num}: {title} ───[/bold yellow]")
    else:
        print(f"\n--- Step {step_num}: {title} ---")


def print_info(message: str):
    if RICH_AVAILABLE:
        console.print(f"[blue][INFO][/blue] {message}")
    else:
        print(f"[INFO] {message}")


def print_success(message: str):
    if RICH_AVAILABLE:
        console.print(f"[bold green][SUCCESS][/bold green] {message}")
    else:
        print(f"[SUCCESS] {message}")


def print_warning(message: str):
    if RICH_AVAILABLE:
        console.print(f"[bold yellow][WARNING][/bold yellow] {message}")
    else:
        print(f"[WARNING] {message}")


def print_error(message: str):
    if RICH_AVAILABLE:
        console.print(f"[bold red][ERROR][/bold red] {message}")
    else:
        print(f"[ERROR] {message}")


def display_server_table(servers: List[Dict[str, Any]], title: str = "iLO Inventory & Firmware Status"):
    """Render a formatted table of all servers and their firmware versions."""
    if RICH_AVAILABLE:
        table = Table(title=title, title_style="bold cyan", header_style="bold magenta")
        table.add_column("#", justify="center", style="dim", width=4)
        table.add_column("Server Name", style="bold white")
        table.add_column("iLO IP", justify="center", style="cyan")
        table.add_column("Config Gen", justify="center", style="yellow")
        table.add_column("Current Firmware", style="bold green")
        table.add_column("Server Model", style="white")
        table.add_column("Status", justify="center")

        for idx, s in enumerate(servers, 1):
            status = s.get("status", "Pending")
            if "ONLINE" in status.upper() or "CHECKED" in status.upper() or "OK" in status.upper():
                status_colored = f"[green]{status}[/green]"
            elif "FAIL" in status.upper() or "ERROR" in status.upper() or "UNREACHABLE" in status.upper():
                status_colored = f"[red]{status}[/red]"
            else:
                status_colored = f"[dim]{status}[/dim]"

            fw = s.get("current_fw") or "[dim]Not checked[/dim]"
            model = s.get("server_model") or s.get("detected_model") or "N/A"

            table.add_row(
                str(idx),
                s.get("server_name", f"Server-{idx}"),
                s.get("ilo_ip", "Unknown"),
                s.get("ilo_type", "iLO5"),
                fw,
                model,
                status_colored
            )
        console.print(table)
    else:
        print(f"\n{title}")
        print(f"{'#':<4} {'Server Name':<20} {'iLO IP':<16} {'Gen':<6} {'Current Firmware':<22} {'Status'}")
        print("-" * 80)
        for idx, s in enumerate(servers, 1):
            fw = s.get("current_fw") or "Not checked"
            print(f"{idx:<4} {s.get('server_name', ''):<20} {s.get('ilo_ip', ''):<16} {s.get('ilo_type', ''):<6} {fw:<22} {s.get('status', '')}")


def display_firmware_files_table(files: List[Any], title: str = "Available Local Firmware Files"):
    """Display discovered firmware files in the local directory."""
    if RICH_AVAILABLE:
        table = Table(title=title, title_style="bold cyan", header_style="bold blue")
        table.add_column("#", justify="center", style="dim", width=4)
        table.add_column("Filename", style="bold white")
        table.add_column("Size", justify="right", style="cyan")
        table.add_column("Target iLO", justify="center", style="yellow")
        table.add_column("Detected Ver", justify="center", style="green")
        table.add_column("Signature (.compsig)", justify="center")

        for idx, f in enumerate(files, 1):
            d = f.to_dict() if hasattr(f, "to_dict") else f
            compsig_str = "[green]Yes[/green]" if d.get("has_compsig") else "[dim]Embedded[/dim]"
            table.add_row(
                str(idx),
                d.get("filename", ""),
                f"{d.get('size_mb', 0)} MB",
                d.get("detected_type", "Unknown"),
                d.get("version_hint") or "N/A",
                compsig_str
            )
        console.print(table)
    else:
        print(f"\n{title}")
        print(f"{'#':<4} {'Filename':<35} {'Size':<10} {'Target':<10} {'Version'}")
        print("-" * 70)
        for idx, f in enumerate(files, 1):
            d = f.to_dict() if hasattr(f, "to_dict") else f
            print(f"{idx:<4} {d.get('filename', ''):<35} {str(d.get('size_mb', 0)) + ' MB':<10} {d.get('detected_type', ''):<10} {d.get('version_hint', '')}")


def display_results_summary_table(results: List[Dict[str, Any]], title: str = "iLO Firmware Upgrade Final Summary"):
    """Display the before vs after comparison summary table."""
    if RICH_AVAILABLE:
        table = Table(title=title, title_style="bold green", header_style="bold white")
        table.add_column("Server Name", style="bold white")
        table.add_column("iLO IP", justify="center", style="cyan")
        table.add_column("Type", justify="center", style="yellow")
        table.add_column("Previous Firmware", style="dim")
        table.add_column("Upgraded Firmware", style="bold green")
        table.add_column("Reset & Verified", justify="center")
        table.add_column("Result Status", justify="center")

        for r in results:
            status = r.get("status", "Unknown")
            if "SUCCESS" in status.upper():
                status_str = f"[bold green]{status}[/bold green]"
            elif "FAIL" in status.upper() or "ERROR" in status.upper():
                status_str = f"[bold red]{status}[/bold red]"
            else:
                status_str = f"[yellow]{status}[/yellow]"

            reset_ver = r.get("reset_verified", "No")
            reset_str = f"[green]{reset_ver}[/green]" if "YES" in reset_ver.upper() else f"[dim]{reset_ver}[/dim]"

            table.add_row(
                r.get("server_name", ""),
                r.get("ilo_ip", ""),
                r.get("ilo_type", ""),
                r.get("initial_fw", "N/A"),
                r.get("new_fw", "N/A"),
                reset_str,
                status_str
            )
        console.print("\n")
        console.print(table)
    else:
        print(f"\n{'=' * 85}")
        print(f"  {title}")
        print(f"{'=' * 85}")
        print(f"{'Server Name':<20} {'iLO IP':<15} {'Previous FW':<18} {'Upgraded FW':<18} {'Status'}")
        print("-" * 85)
        for r in results:
            print(f"{r.get('server_name', ''):<20} {r.get('ilo_ip', ''):<15} {r.get('initial_fw', 'N/A'):<18} {r.get('new_fw', 'N/A'):<18} {r.get('status', '')}")


def prompt_user_selection(max_idx: int) -> List[int]:
    """
    Prompt the user to select which servers to update.
    Supports: single ('1'), list ('1,2,4'), range ('1-3'), or 'ALL'.
    Returns 0-based indices list.
    """
    while True:
        if RICH_AVAILABLE:
            raw = Prompt.ask(
                f"[bold cyan]Select servers to update[/bold cyan] (e.g. [yellow]1[/yellow], [yellow]1,3[/yellow], [yellow]1-3[/yellow], or [bold green]ALL[/bold green])",
                default="ALL"
            )
        else:
            raw = input(f"Select servers to update (e.g. 1, 1,3, 1-3, or ALL) [ALL]: ").strip() or "ALL"

        raw = raw.strip().upper()
        if raw == "ALL":
            return list(range(max_idx))

        selected = set()
        valid = True
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for p in parts:
            if "-" in p:
                sub_parts = p.split("-")
                if len(sub_parts) == 2 and sub_parts[0].isdigit() and sub_parts[1].isdigit():
                    start, end = int(sub_parts[0]), int(sub_parts[1])
                    if 1 <= start <= max_idx and 1 <= end <= max_idx and start <= end:
                        for i in range(start, end + 1):
                            selected.add(i - 1)
                    else:
                        valid = False
                else:
                    valid = False
            elif p.isdigit():
                val = int(p)
                if 1 <= val <= max_idx:
                    selected.add(val - 1)
                else:
                    valid = False
            else:
                valid = False

        if valid and selected:
            return sorted(list(selected))

        print_error(f"Invalid selection: '{raw}'. Enter server numbers between 1 and {max_idx}, or 'ALL'.")


def confirm_action(prompt_text: str, default: bool = True) -> bool:
    """Prompt the user for a Yes/No confirmation."""
    if RICH_AVAILABLE:
        return Confirm.ask(f"[bold yellow]{prompt_text}[/bold yellow]", default=default)
    else:
        choice = input(f"{prompt_text} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not choice:
            return default
        return choice.startswith("y")
