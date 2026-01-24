"""Dependency checking for PR Fixer.

This module provides functions to check for required external dependencies
(git, gh CLI, claude CLI) and provide user-friendly error messages with
installation instructions.
"""

import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional


@dataclass
class DependencyInfo:
    """Information about a required dependency."""
    name: str
    command: str
    description: str
    install_url: str
    install_instructions: str
    version_flag: str = "--version"


# Required dependencies for pr-fixer
DEPENDENCIES = {
    "git": DependencyInfo(
        name="Git",
        command="git",
        description="version control system",
        install_url="https://git-scm.com/downloads",
        install_instructions="Install Git from https://git-scm.com/downloads or use your package manager.",
        version_flag="--version",
    ),
    "gh": DependencyInfo(
        name="GitHub CLI",
        command="gh",
        description="GitHub command-line interface",
        install_url="https://cli.github.com/",
        install_instructions=(
            "Install GitHub CLI from https://cli.github.com/\n"
            "  macOS: brew install gh\n"
            "  Windows: winget install --id GitHub.cli\n"
            "  Linux: See https://github.com/cli/cli/blob/trunk/docs/install_linux.md"
        ),
        version_flag="--version",
    ),
    "claude": DependencyInfo(
        name="Claude CLI",
        command="claude",
        description="Claude AI command-line interface",
        install_url="https://docs.anthropic.com/en/docs/claude-code",
        install_instructions=(
            "Install Claude CLI:\n"
            "  npm install -g @anthropic-ai/claude-code\n"
            "  See https://docs.anthropic.com/en/docs/claude-code for details."
        ),
        version_flag="--version",
    ),
}


class DependencyError(Exception):
    """Raised when a required dependency is missing or not properly configured."""

    def __init__(self, dependency: DependencyInfo, details: str = ""):
        self.dependency = dependency
        self.details = details
        message = self._build_message()
        super().__init__(message)

    def _build_message(self) -> str:
        """Build a user-friendly error message with installation instructions."""
        lines = [
            f"{self.dependency.name} ({self.dependency.command}) is not available.",
            "",
        ]
        if self.details:
            lines.append(f"Details: {self.details}")
            lines.append("")
        lines.append(self.dependency.install_instructions)
        return "\n".join(lines)


class AuthenticationError(Exception):
    """Raised when a tool requires authentication that hasn't been set up."""

    def __init__(self, tool: str, message: str, instructions: str):
        self.tool = tool
        self.instructions = instructions
        full_message = f"{message}\n\n{instructions}"
        super().__init__(full_message)


def check_command_exists(command: str) -> bool:
    """
    Check if a command exists in the system PATH.

    Args:
        command: The command name to check

    Returns:
        True if the command exists, False otherwise
    """
    return shutil.which(command) is not None


def get_command_version(command: str, version_flag: str = "--version") -> Optional[str]:
    """
    Get the version string of a command.

    Args:
        command: The command to get version for
        version_flag: The flag to use for version (default: --version)

    Returns:
        Version string if successful, None otherwise
    """
    try:
        result = subprocess.run(
            [command, version_flag],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Return first non-empty line of output
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    return line.strip()
            # Fallback to stderr if stdout is empty
            for line in result.stderr.strip().split("\n"):
                if line.strip():
                    return line.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None


def check_dependency(dep_name: str) -> tuple[bool, Optional[str]]:
    """
    Check if a specific dependency is available.

    Args:
        dep_name: The dependency name (key in DEPENDENCIES dict)

    Returns:
        Tuple of (is_available, version_string or None)

    Raises:
        ValueError: If the dependency name is not recognized
    """
    if dep_name not in DEPENDENCIES:
        raise ValueError(f"Unknown dependency: {dep_name}")

    dep = DEPENDENCIES[dep_name]

    if not check_command_exists(dep.command):
        return False, None

    version = get_command_version(dep.command, dep.version_flag)
    return True, version


def check_gh_authentication() -> tuple[bool, str]:
    """
    Check if the GitHub CLI is authenticated.

    Returns:
        Tuple of (is_authenticated, status_message)
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Extract the account info from output
            output = result.stdout + result.stderr
            return True, "Authenticated"
        else:
            return False, result.stderr.strip() if result.stderr else "Not authenticated"
    except FileNotFoundError:
        return False, "gh CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "Timed out checking authentication"
    except Exception as e:
        return False, str(e)


def require_dependency(dep_name: str) -> str:
    """
    Require that a dependency is available, raising an error if not.

    Args:
        dep_name: The dependency name to check

    Returns:
        The version string of the dependency

    Raises:
        DependencyError: If the dependency is not available
    """
    if dep_name not in DEPENDENCIES:
        raise ValueError(f"Unknown dependency: {dep_name}")

    dep = DEPENDENCIES[dep_name]
    is_available, version = check_dependency(dep_name)

    if not is_available:
        raise DependencyError(dep)

    return version or "unknown version"


def check_all_dependencies(verbose: bool = False) -> dict[str, tuple[bool, Optional[str]]]:
    """
    Check all required dependencies and return their status.

    Args:
        verbose: If True, include version information

    Returns:
        Dictionary mapping dependency names to (is_available, version) tuples
    """
    results = {}
    for dep_name in DEPENDENCIES:
        is_available, version = check_dependency(dep_name)
        results[dep_name] = (is_available, version)
    return results


def require_all_dependencies() -> None:
    """
    Require that all dependencies are available.

    Raises:
        DependencyError: If any dependency is missing (reports first missing one)
    """
    missing = []
    for dep_name in DEPENDENCIES:
        is_available, _ = check_dependency(dep_name)
        if not is_available:
            missing.append(DEPENDENCIES[dep_name])

    if missing:
        # Raise error for the first missing dependency
        raise DependencyError(missing[0])


def require_gh_authentication() -> None:
    """
    Require that the GitHub CLI is authenticated.

    Raises:
        AuthenticationError: If gh is not authenticated
        DependencyError: If gh is not installed
    """
    # First check gh is installed
    require_dependency("gh")

    # Then check authentication
    is_authenticated, message = check_gh_authentication()
    if not is_authenticated:
        raise AuthenticationError(
            tool="GitHub CLI",
            message=f"GitHub CLI is not authenticated: {message}",
            instructions=(
                "Please authenticate with GitHub CLI:\n"
                "  gh auth login\n\n"
                "Follow the prompts to authenticate with your GitHub account."
            ),
        )


def format_dependency_status(results: dict[str, tuple[bool, Optional[str]]]) -> str:
    """
    Format dependency check results for display.

    Args:
        results: Dictionary from check_all_dependencies

    Returns:
        Formatted string showing dependency status
    """
    lines = ["Dependency Status:", ""]
    for dep_name, (is_available, version) in results.items():
        dep = DEPENDENCIES[dep_name]
        if is_available:
            version_str = f" ({version})" if version else ""
            lines.append(f"  [OK] {dep.name}{version_str}")
        else:
            lines.append(f"  [MISSING] {dep.name}")
    return "\n".join(lines)
