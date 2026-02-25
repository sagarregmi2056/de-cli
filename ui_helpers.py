"""
UI helper functions for colored terminal output and formatted prompts.
"""

from colorama import Fore, Style, init

# Initialize colorama for cross-platform color support
init(autoreset=True)


def print_header(text: str) -> None:
    """Print a colored header with border."""
    border = "=" * (len(text) + 4)
    print(f"\n{Fore.CYAN}{border}")
    print(f"{Fore.CYAN}  {text}")
    print(f"{Fore.CYAN}{border}{Style.RESET_ALL}\n")


def print_success(text: str) -> None:
    """Print success message in green."""
    print(f"{Fore.GREEN}✓ {text}{Style.RESET_ALL}")


def print_error(text: str) -> None:
    """Print error message in red."""
    print(f"{Fore.RED}✗ {text}{Style.RESET_ALL}")


def print_warning(text: str) -> None:
    """Print warning message in yellow."""
    print(f"{Fore.YELLOW}⚠ {text}{Style.RESET_ALL}")


def print_info(text: str) -> None:
    """Print info message in blue."""
    print(f"{Fore.BLUE}ℹ {text}{Style.RESET_ALL}")


def print_market_card(
    title: str,
    market_type: str,
    end_date: str,
    market_id: str,
    slug: str | None = None,
    source_event_id: str | None = None,
    odds: dict[str, float] | None = None,
    token_ids: dict[str, str] | None = None,
) -> None:
    """
    Print a formatted market card with border and odds/outcome prices.

    Here `odds` is expected to be a mapping of outcome -> price (0.0–1.0),
    e.g. the Gamma `outcomePrices` snapshot for Yes / No or team outcomes.
    """
    border = "─" * 70
    print(f"\n{Fore.MAGENTA}{border}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Market:{Style.RESET_ALL} {Fore.WHITE}{title}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Type:{Style.RESET_ALL} {Fore.YELLOW}{market_type}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}End Date:{Style.RESET_ALL} {Fore.WHITE}{end_date}{Style.RESET_ALL}")
    if slug:
        print(f"{Fore.CYAN}Slug:{Style.RESET_ALL} {Fore.WHITE}{slug}{Style.RESET_ALL}")
    if source_event_id:
        print(f"{Fore.CYAN}Source ID:{Style.RESET_ALL} {Fore.WHITE}{source_event_id}{Style.RESET_ALL}")
    
    # Display odds / outcome prices if available
    if odds:
        print(f"{Fore.CYAN}Current Odds (outcome prices):{Style.RESET_ALL}")
        for outcome_name, price in odds.items():
            # price is 0.0–1.0; also show in cents for convenience
            cents = price * 100
            print(
                f"  {Fore.GREEN}{outcome_name}:{Style.RESET_ALL} "
                f"{Fore.WHITE}{price:.4f} ({cents:.1f}¢){Style.RESET_ALL}"
            )
    else:
        print(f"{Fore.YELLOW}Odds:{Style.RESET_ALL} {Fore.WHITE}Not available{Style.RESET_ALL}")

    # Display token IDs (CLOB token ids) if available
    if token_ids:
        print(f"{Fore.CYAN}CLOB Token IDs:{Style.RESET_ALL}")
        for outcome_name, token_id in token_ids.items():
            print(
                f"  {Fore.GREEN}{outcome_name}:{Style.RESET_ALL} "
                f"{Fore.WHITE}{token_id}{Style.RESET_ALL}"
            )
    
    print(f"{Fore.CYAN}Mongo ID:{Style.RESET_ALL} {Fore.WHITE}{market_id}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}{border}{Style.RESET_ALL}\n")


def prompt_choice(prompt: str, options: list[str], allow_exit: bool = True) -> str | None:
    """
    Display a numbered choice menu and return the selected option or None if exit.
    
    Args:
        prompt: The question to ask
        options: List of option strings
        allow_exit: If True, adds 'x' for exit option
    
    Returns:
        Selected option number as string, or None if user chose exit
    """
    print(f"\n{Fore.CYAN}{prompt}{Style.RESET_ALL}")
    for i, opt in enumerate(options, 1):
        print(f"  {Fore.YELLOW}{i}{Style.RESET_ALL}) {opt}")
    
    if allow_exit:
        print(f"  {Fore.RED}x{Style.RESET_ALL}) Exit")
    
    while True:
        choice = input(f"{Fore.GREEN}Choose an option{Style.RESET_ALL} [{'/'.join(str(i) for i in range(1, len(options) + 1))}{', x' if allow_exit else ''}]: ").strip().lower()
        
        if allow_exit and choice == "x":
            return None
        
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return choice
        
        print_error(f"Invalid choice. Please enter 1-{len(options)}" + (" or 'x' to exit" if allow_exit else ""))


def prompt_yes_no(prompt: str, default: bool = True, allow_back: bool = False) -> str | None:
    """
    Prompt for yes/no with optional back/exit.
    
    Returns:
        'y' for yes, 'n' for no, 'b' for back (if allowed), None for exit
    """
    default_text = "Y/n" if default else "y/N"
    back_text = "/b (back)" if allow_back else ""
    exit_text = "/x (exit)"
    
    while True:
        ans = input(f"{Fore.CYAN}{prompt}{Style.RESET_ALL} [{default_text}{back_text}{exit_text}]: ").strip().lower()
        
        if ans == "x":
            return None  # Exit
        if allow_back and ans == "b":
            return "b"  # Go back
        if ans in ("", "y", "yes"):
            return "y"
        if ans in ("n", "no"):
            return "n"
        
        print_error("Invalid input. Please enter Y/n" + ("/b" if allow_back else "") + "/x")


def print_separator() -> None:
    """Print a visual separator line."""
    print(f"{Fore.MAGENTA}{'─' * 70}{Style.RESET_ALL}")


def print_structured_summary(structured: dict) -> None:
    """Pretty-print key fields from structured_event for 1v1 or teams."""
    event_type = structured.get("event_type", "unknown")
    event = structured.get("event", {})
    candidates = structured.get("candidates", [])

    print_separator()
    print(f"{Fore.CYAN}Structured Event (type={event_type}){Style.RESET_ALL}")

    if event:
        print(f"{Fore.YELLOW}Event:{Style.RESET_ALL}")
        for k in ["event_name", "event_date", "event_time", "event_location", "event_timezone", "event_lat", "event_lon"]:
            if k in event:
                print(f"  {k}: {event.get(k)}")

    if candidates:
        print(f"{Fore.YELLOW}Candidates:{Style.RESET_ALL}")
        for idx, cand in enumerate(candidates, 1):
            # For teams, each candidate is a team with nested captain/coach
            if event_type == "teams" and "team_name" in cand:
                team_name = cand.get("team_name", "Unknown Team")
                print(f"  #{idx}: {team_name}")
                
                # Display captain information
                captain = cand.get("captain")
                if captain:
                    print(f"      Captain:")
                    captain_name = captain.get("name", "Unknown")
                    print(f"        name: {captain_name}")
                    for k in [
                        "birth_name",
                        "birth_date",
                        "birth_time",
                        "birth_place",
                        "birth_country",
                        "birth_timezone",
                        "lat",
                        "lon",
                        "lat_dir",
                        "lon_dir",
                        "gender",
                    ]:
                        if k in captain and captain.get(k) is not None:
                            print(f"        {k}: {captain.get(k)}")
                else:
                    print(f"      Captain: Not available")
                
                # Display coach information
                coach = cand.get("coach")
                if coach:
                    print(f"      Coach:")
                    coach_name = coach.get("name", "Unknown")
                    print(f"        name: {coach_name}")
                    for k in [
                        "birth_name",
                        "birth_date",
                        "birth_time",
                        "birth_place",
                        "birth_country",
                        "birth_timezone",
                        "lat",
                        "lon",
                        "lat_dir",
                        "lon_dir",
                        "gender",
                    ]:
                        if k in coach and coach.get(k) is not None:
                            print(f"        {k}: {coach.get(k)}")
                else:
                    print(f"      Coach: Not available")
            else:
                # For 1v1 or other types, display candidate fields directly
                name = cand.get("name") or cand.get("team_name") or "Unknown"
                print(f"  #{idx}: {name}")
                for k in [
                    "role",
                    "team_name",
                    "birth_name",
                    "birth_date",
                    "birth_time",
                    "birth_place",
                    "birth_country",
                    "birth_timezone",
                    "lat",
                    "lon",
                    "lat_dir",
                    "lon_dir",
                    "gender",
                ]:
                    if k in cand and cand.get(k) is not None:
                        print(f"      {k}: {cand.get(k)}")
    print_separator()

