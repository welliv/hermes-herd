"""What follows you, and what stays on this machine.

The single hardest part of syncing an agent is that "your config" is not one
thing: a Docker socket path, a webapp port and a Telegram bot token mean
different things on a laptop than on a server. Herd therefore merges config
*per key* and keeps a curated set of keys device-local by default, with one
user-editable policy file to override any of it.

Everything here is deliberately data, not code: `hermes sync policy` prints the
effective rules, so a user can see exactly why a key did or did not move.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from . import yamlutil

# Keyed by dotted config path. Anything matched is never read from or written to
# another machine. Prefix matches are intentional: a new Docker tuning knob ships
# in Hermes and stays local without Herd needing a release.
DEFAULT_LOCAL_ONLY: tuple[str, ...] = (
    # Where commands run, and which container runtime is underneath.
    "terminal.backend",
    "terminal.cwd",
    "terminal.home_mode",
    "terminal.docker_*",
    "terminal.container_*",
    "terminal.lifetime_seconds",
    # Storage and locks live on the machine that owns them.
    "database.*",
    "runtime.*",
    "attachments.*",
    # A web app is bound to one host and one port.
    "webapp.*",
    "gateway.host",
    "gateway.port",
    "gateway.service_install_choice",
    "gateway.profile_routes",
    "gateway.unmanaged_idle_exit_seconds",
    # Credentials and per-machine login state are never copied implicitly.
    "auth.*",
    "browser.*",
    "plugins.entries.*",
    "updates.*",
    "onboarding.*",
    "telemetry.*",
    # Two machines polling one bot produce double replies; connect each one.
    "platforms.*",
)

# Env vars that describe a machine rather than a person. Values are copied only
# when a user explicitly asks for them.
DEFAULT_SECRET_SKIP: tuple[str, ...] = (
    # A bot token makes whichever machine holds it start answering. Two machines
    # with the same token both answer every message, so these stay put even
    # though they are secrets the user would otherwise want to carry.
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL*", "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "MATRIX_ACCESS_TOKEN", "SIGNAL_*",
    "WHATSAPP_*", "TWILIO_*", "TEAMS_*",
    "PATH", "HOME", "USER", "SHELL", "PWD", "OLDPWD", "LANG", "LC_*", "TZ", "TERM",
    "HOSTNAME", "DISPLAY", "XAUTHORITY", "XDG_*", "SSH_*", "GPG_*",
    "HERMES_HOME", "HERMES_INSTALL*", "HERMES_DASHBOARD_*", "HERMES_WEBAPP_*",
    "*_PROXY", "NO_PROXY", "LD_*", "DYLD_*", "VIRTUAL_ENV", "CONDA_*",
)

DEFAULT_SKILL_SKIP: tuple[str, ...] = ()

POLICY_FILENAME = "policy.yaml"
POLICY_HEADER = """\
# Herd sync policy — this file is per machine and never synced.
#
# local_only: config paths this machine keeps to itself (dotted paths, * wildcards)
# shared:     paths that are local-only by default but should follow you here
# scope:      profile = settings, skills and memory; knowledge = skills and memory only
# secret_skip: .env keys that stay on this machine
# sync_secrets: ignored. API keys are not synced; Herd never reads .env.
#
# Print the effective rules with: hermes sync policy
"""


def _matches(path: str, pattern: str) -> bool:
    """A pattern names a key and everything under it: `platforms.telegram`
    covers `platforms.telegram.home_channel.chat_id`."""
    if fnmatchcase(path, pattern):
        return True
    return path.startswith(pattern.rstrip(".") + ".")


class Policy:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.local_only = list(DEFAULT_LOCAL_ONLY) + [str(p) for p in data.get("local_only") or []]
        self.shared = [str(p) for p in data.get("shared") or []]
        self.secret_skip = list(DEFAULT_SECRET_SKIP) + [str(p) for p in data.get("secret_skip") or []]
        self.skill_skip = list(DEFAULT_SKILL_SKIP) + [str(p) for p in data.get("skip_skills") or []]
        scope = str(data.get("scope") or "profile").lower()
        self.scope = scope if scope in ("profile", "knowledge") else "profile"
        # Older policy files may say true. It is not honored: this build does
        # not read or write ~/.hermes/.env (catalog rule 11).
        self.sync_secrets = False
        self.auto_pull = bool(data.get("auto_pull", True))
        self.auto_push = bool(data.get("auto_push", True))

    # ── matching ─────────────────────────────────────────────────────────────
    def is_local_only(self, path: str) -> bool:
        if any(_matches(path, p) for p in self.shared):
            return False
        return any(_matches(path, p) for p in self.local_only)

    def secret_allowed(self, name: str) -> bool:
        """True when the skip rules do not exclude *name*.

        Credential sync is unsupported, so this only describes the skip list a
        future transport would have to honor. Nothing in this build reads it
        off disk.
        """
        return not any(fnmatchcase(name, p) for p in self.secret_skip)

    def wants(self, kind: str) -> bool:
        """Does this machine take an item of *kind* from the herd?

        `profile` (the default) syncs everything the other rules allow.
        `knowledge` syncs what you taught the agent — skills and memory — and
        leaves settings alone, for people who run each machine as its own
        profile but are tired of explaining themselves three times.
        """
        return self.scope != "knowledge" or kind in ("skill", "memory")

    def skill_allowed(self, name: str) -> bool:
        return not any(fnmatchcase(name, p) for p in self.skill_skip)

    # ── persistence ──────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path) -> "Policy":
        try:
            data = yamlutil.safe_load(path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return cls()
        except Exception:
            # A corrupt policy must not silently change what syncs: fall back to
            # the safe defaults and let `hermes sync doctor` report the bad file.
            return cls()
        return cls(data if isinstance(data, dict) else {})

    def to_dict(self) -> dict:
        extra_local = self.local_only[len(DEFAULT_LOCAL_ONLY) :]
        extra_skip = self.secret_skip[len(DEFAULT_SECRET_SKIP) :]
        extra_skills = self.skill_skip[len(DEFAULT_SKILL_SKIP) :]
        return {
            "local_only": extra_local,
            "shared": self.shared,
            "secret_skip": extra_skip,
            "skip_skills": extra_skills,
            "scope": self.scope,
            "sync_secrets": self.sync_secrets,
            "auto_pull": self.auto_pull,
            "auto_push": self.auto_push,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = yamlutil.safe_dump(self.to_dict())
        # Keep the header on every write so the file explains itself a year later.
        path.write_text(POLICY_HEADER + "\n" + body, encoding="utf-8")
        path.chmod(0o600)
