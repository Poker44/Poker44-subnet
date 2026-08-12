import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCHER = ROOT / "scripts/validator/update/auto_update_validator.sh"
ENV_MIGRATION = ROOT / "scripts/validator/update/migrate_validator_env.sh"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def write_version(repo: Path, version: str) -> None:
    package = repo / "poker44"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text(
        f'VALIDATOR_DEPLOY_VERSION = "{version}"\n', encoding="utf-8"
    )


def test_watcher_applies_a_new_deploy_version_once(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    publisher = tmp_path / "publisher"
    validator = tmp_path / "validator"
    run("git", "init", "--bare", str(origin), cwd=tmp_path)
    run("git", "init", "-b", "main", str(publisher), cwd=tmp_path)
    run("git", "config", "user.name", "test", cwd=publisher)
    run("git", "config", "user.email", "test@example.invalid", cwd=publisher)
    write_version(publisher, "0.2.0")
    run("git", "add", ".", cwd=publisher)
    run("git", "commit", "-m", "release 0.2.0", cwd=publisher)
    run("git", "remote", "add", "origin", str(origin), cwd=publisher)
    run("git", "push", "-u", "origin", "main", cwd=publisher)
    run("git", "clone", "--branch", "main", str(origin), str(validator), cwd=tmp_path)

    write_version(publisher, "0.2.1")
    run("git", "add", ".", cwd=publisher)
    run("git", "commit", "-m", "release 0.2.1", cwd=publisher)
    run("git", "push", "origin", "main", cwd=publisher)

    updater = tmp_path / "apply-update.sh"
    updater.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'git fetch origin "$TARGET_BRANCH" --quiet\n'
        'git merge --ff-only "origin/$TARGET_BRANCH"\n',
        encoding="utf-8",
    )
    updater.chmod(0o700)
    state = tmp_path / "watcher.state"
    environment = {
        **os.environ,
        "AUTO_UPDATE_RUN_ONCE": "true",
        "AUTO_UPDATE_UPDATE_SCRIPT": str(updater),
        "STATE_FILE": str(state),
        "TARGET_BRANCH": "main",
    }
    result = subprocess.run(
        ["bash", str(WATCHER)],
        cwd=validator,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )

    assert 'VALIDATOR_DEPLOY_VERSION = "0.2.1"' in (
        validator / "poker44/__init__.py"
    ).read_text(encoding="utf-8")
    assert "LAST_APPLIED_VALIDATOR_DEPLOY_VERSION=0.2.1" in state.read_text(
        encoding="utf-8"
    )
    assert state.stat().st_mode & 0o777 == 0o600
    assert "New Poker44 deploy version detected" in result.stdout
    assert "bash -x" not in result.stdout + result.stderr


def test_validator_runner_enables_the_watcher_by_default() -> None:
    runner = (ROOT / "scripts/validator/run/run_vali.sh").read_text(encoding="utf-8")
    assert 'AUTO_UPDATE_ENABLED="${AUTO_UPDATE_ENABLED:-true}"' in runner
    assert 'pm2 start bash --name "$AUTO_UPDATE_PM2_NAME"' in runner


def migrated_burn(value: str, env_file: Path) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                'source "$1"; migrate_transition_burn_default "$2" >/dev/null; '
                'printf "%s" "$POKER44_BURN_FRACTION"'
            ),
            "burn-migration",
            str(ENV_MIGRATION),
            str(env_file),
        ],
        env={**os.environ, "POKER44_BURN_FRACTION": value},
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def test_update_migrates_only_the_inherited_old_burn_default(tmp_path: Path) -> None:
    implicit_env = tmp_path / "implicit.env"
    implicit_env.write_text("POKER44_POLL_INTERVAL_SECONDS=300\n", encoding="utf-8")
    explicit_env = tmp_path / "explicit.env"
    explicit_env.write_text("POKER44_BURN_FRACTION=0.30\n", encoding="utf-8")

    assert migrated_burn("0.90", implicit_env) == "0.00"
    assert migrated_burn("0.70", implicit_env) == "0.00"
    assert migrated_burn("0.30", implicit_env) == "0.00"
    assert migrated_burn("0.30", explicit_env) == "0.30"
    assert migrated_burn("0.80", implicit_env) == "0.80"
