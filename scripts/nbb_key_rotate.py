"""NBB CBSO subscription key rotation via the developer portal.

NBB silently rotates Primary keys on its developer portal at irregular
intervals (twice within 24h on 2026-04-17). When that happens, the
platform's NBB calls start returning 401/403 until the keys in
`.env.production` are refreshed.

This script automates the manual portal dance:
  1. Log in to https://developer.cbso.nbb.be with the configured creds
  2. Open each subscription's profile page
  3. Click "Show" on the Primary key (necessary — values render obscured
     until "Show" is pressed; "Regenerate" fires a server call but the
     resulting key only appears in the DOM after a "Show" reveal)
  4. Click "Regenerate" on the Primary key
  5. Click "Show" again to read the new value
  6. Write the three new keys to /opt/leadpeek/.env.production and .env
     (with timestamped backups). Container recreate is left to the
     wrapper script so this stays single-purpose.

Usage:
  python scripts/nbb_key_rotate.py --dry-run   # log in + dump current keys
  python scripts/nbb_key_rotate.py --rotate    # full rotation

Env (read from /data/.env.production when run inside the playwright
container; falls back to process env otherwise):
  NBB_PORTAL_URL              (default https://developer.cbso.nbb.be)
  NBB_PORTAL_USER             portal email
  NBB_PORTAL_PASSWORD         portal password
  NBB_ROTATE_HEADLESS         "false" to watch the run in a real window
  NBB_ROTATE_DEBUG_DIR        where to drop step-by-step screenshots
                              (default /data/scripts/_rotate_debug)
  NBB_ENV_FILES               comma-separated env files to update
                              (default /data/.env.production,/data/.env)

Security:
  - Credentials never touch stdout/stderr or screenshots beyond
    "logged in as <user>".
  - New keys are masked in logs (first/last 4 chars only).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s nbb_rotate \u2014 %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nbb_rotate")


SUBSCRIPTION_ENV_MAP = {
    # Match by case-insensitive substring against the subscription name as
    # it appears in the portal. The NBB portal labels them with the
    # CLIENT-…-SUB-… prefix so we anchor on the suffix only.
    "AuthenticData": "NBB_AUTHENTIC_KEY",
    "Extracts": "NBB_EXTRACT_KEY",
    "AuthenticArchiveData": "NBB_ARCHIVE_KEY",
}

KEY_REGEX = re.compile(r"\b[a-f0-9]{32}\b")


# ----------------------------------------------------------------------
# .env file helpers
# ----------------------------------------------------------------------

def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _patch_env_file(path: Path, updates: dict[str, str]) -> None:
    """In-place update specific KEY=VALUE lines in a .env file. Preserves
    comments, blank lines, ordering, and any unrelated keys."""
    if not path.exists():
        log.warning("env file %s does not exist; skipping", path)
        return
    backup = path.with_suffix(path.suffix + f".bak-pre-rotate-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    backup.write_bytes(path.read_bytes())

    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    new_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw)
            continue
        k = stripped.split("=", 1)[0].strip()
        if k in updates:
            new_lines.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            new_lines.append(raw)
    # Append any new keys not present in the file
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Updated %s (backup: %s)", path, backup.name)


def _mask(s: str) -> str:
    if not s or len(s) < 8:
        return "<empty>"
    return f"{s[:4]}\u2026{s[-4:]}"


# ----------------------------------------------------------------------
# Playwright dance
# ----------------------------------------------------------------------

def _resolve_env_files(raw: str) -> list[Path]:
    return [Path(p.strip()) for p in raw.split(",") if p.strip()]


def _expect_text_or_fail(page, locator, what: str, timeout_ms: int = 15000):
    try:
        locator.first.wait_for(timeout=timeout_ms)
    except Exception as e:
        log.error("Could not find %s on %s: %s", what, page.url, e)
        raise


def _save_screenshot(page, debug_dir: Path, name: str) -> None:
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%H%M%S")
        out = debug_dir / f"{ts}_{name}.png"
        page.screenshot(path=str(out), full_page=True)
        log.info("Screenshot \u2192 %s", out)
    except Exception:
        log.debug("screenshot failed", exc_info=True)


def _login(page, portal_url: str, user: str, password: str, debug_dir: Path) -> None:
    signin_url = portal_url.rstrip("/") + "/signin"
    log.info("Navigating to %s", signin_url)
    page.goto(signin_url, wait_until="domcontentloaded", timeout=30000)
    _save_screenshot(page, debug_dir, "01_signin")

    # Azure APIM developer portal sign-in form
    email_box = page.locator(
        "input[type='email'], input[name='email'], input[name='username'], input#email"
    ).first
    pwd_box = page.locator(
        "input[type='password'], input[name='password'], input#password"
    ).first

    _expect_text_or_fail(page, email_box, "email input")
    email_box.fill(user)
    pwd_box.fill(password)
    _save_screenshot(page, debug_dir, "02_filled")

    # Try button text variants the APIM portal may use, ordered by likelihood
    submit = page.locator(
        "button[type='submit'], input[type='submit'], button:has-text('Sign in'), "
        "button:has-text('Sign In'), button:has-text('Login'), button:has-text('Aanmelden')"
    ).first
    submit.click()
    log.info("Submitted sign-in form")
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    # Allow the SPA to settle after redirect
    page.wait_for_timeout(2500)
    _save_screenshot(page, debug_dir, "03_after_signin")

    # Quick sanity: URL should no longer be /signin
    if "/signin" in page.url.lower():
        log.error("Still on sign-in page after submit \u2014 login probably failed")
        raise RuntimeError("Sign-in failed")
    log.info("Logged in (now at %s)", page.url)


def _open_profile(page, portal_url: str, debug_dir: Path) -> None:
    profile_url = portal_url.rstrip("/") + "/profile"
    log.info("Opening %s", profile_url)
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2500)
    _save_screenshot(page, debug_dir, "04_profile")
    # Drop the rendered HTML next to the screenshot so failures are debuggable
    try:
        (debug_dir / "04_profile.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        log.debug("html dump failed", exc_info=True)


def _find_subscription_blocks(page) -> list[dict]:
    """Locate active subscription rows on the profile page. The portal
    renders them as <tr> rows in the Subscriptions table. Each active row
    has TWO 'Show / Regenerate' link pairs (Primary then Secondary).
    We only want the Primary, so within each row we select the first
    Show + first Regenerate anchor.

    Returns: [{name, row, primary_show, primary_regen, raw_text}, ...]"""
    blocks: list[dict] = []
    # The profile page has one or more <tr> per subscription. Active rows
    # contain a Primary key cell with both Show and Regenerate links.
    # Filter on:
    #   - row text contains "CLIENT-" (skips empty 'test' rows)
    #   - row text contains "Active" (state)
    #   - row text contains "Primary key" (so we know it has the link pair)
    rows = page.locator("tr").filter(
        has_text=re.compile(r"CLIENT-.*Active.*Primary key", re.DOTALL)
    )
    n = rows.count()
    log.info("Found %d active subscription row(s)", n)
    for i in range(n):
        row = rows.nth(i)
        try:
            text = row.inner_text(timeout=5000)
        except Exception:
            continue
        # Pull the CLIENT-…-<suffix> name from the row text
        m = re.search(r"CLIENT-\d+-SUB-\d+-(\S+)", text)
        name = m.group(0) if m else f"row_{i}"
        # Within this row, the FIRST Show link is for Primary, the SECOND for Secondary.
        primary_show = row.locator("a:has-text('Show'), button:has-text('Show')").first
        primary_regen = row.locator("a:has-text('Regenerate'), button:has-text('Regenerate')").first
        blocks.append({
            "name": name,
            "row": row,
            "primary_show": primary_show,
            "primary_regen": primary_regen,
            "raw_text": text,
        })
    return blocks


def _classify_subscription(label: str) -> str | None:
    """Map a subscription label to one of our env var keys.
    Returns the matching label key (e.g. 'AuthenticData') or None."""
    low = label.lower()
    # Check most-specific suffix first so 'AuthenticArchiveData' isn't
    # accidentally caught by 'AuthenticData'.
    if "authenticarchivedata" in low or ("archive" in low and "authentic" in low):
        return "AuthenticArchiveData"
    if "extract" in low:
        return "Extracts"
    if "authenticdata" in low or ("authentic" in low and "archive" not in low):
        return "AuthenticData"
    return None


def _show_and_read_key(blk: dict, after_action: str, debug_dir: Path, page, idx: int) -> str | None:
    """Click 'Show' on the Primary key, return the revealed value."""
    try:
        blk["primary_show"].click(timeout=5000)
    except Exception:
        log.warning("Could not click Show (%s, row %d) \u2014 already visible?", after_action, idx)
    page.wait_for_timeout(1200)
    _save_screenshot(page, debug_dir, f"sub_{idx}_after_{after_action}_show")

    # Read all 32-hex-char tokens visible inside the row.
    # First match = Primary key (rows are: Primary line, then Secondary line).
    text = blk["row"].inner_text(timeout=5000)
    matches = KEY_REGEX.findall(text)
    if not matches:
        log.warning("No 32-hex key found in row after %s", after_action)
        return None
    return matches[0]


def _regenerate_primary(blk: dict, debug_dir: Path, page, idx: int) -> None:
    blk["primary_regen"].click(timeout=5000)
    log.info("Clicked Regenerate (row %d)", idx)
    page.wait_for_timeout(800)
    # Portal throws up a confirmation dialog — accept it. Some portals use
    # native browser confirm(), which Playwright auto-dismisses unless
    # we register a handler. Register one defensively before clicking.
    confirm = page.locator(
        "button:has-text('Confirm'), button:has-text('Yes'), button:has-text('OK'), "
        "button:has-text('Bevestigen'), button:has-text('Ja')"
    ).first
    try:
        confirm.click(timeout=4000)
        log.info("Confirmed regenerate dialog (row %d)", idx)
    except Exception:
        log.info("No HTML confirm dialog (row %d) \u2014 may have been a native popup auto-accepted", idx)
    page.wait_for_timeout(2000)
    _save_screenshot(page, debug_dir, f"sub_{idx}_after_regen")


def rotate_keys(dry_run: bool) -> dict[str, str]:
    """Returns dict of {ENV_VAR_NAME: new_key_value} after rotation.

    On dry-run, returns the CURRENT key values without rotating."""
    portal_url = os.environ["NBB_PORTAL_URL"].rstrip("/")
    user = os.environ["NBB_PORTAL_USER"]
    password = os.environ["NBB_PORTAL_PASSWORD"]
    headless = os.environ.get("NBB_ROTATE_HEADLESS", "true").lower() != "false"
    debug_dir = Path(os.environ.get("NBB_ROTATE_DEBUG_DIR", "/data/scripts/_rotate_debug"))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright not installed. Run inside the playwright container or `pip install playwright && playwright install chromium`.")
        sys.exit(2)

    new_keys: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            _login(page, portal_url, user, password, debug_dir)
            _open_profile(page, portal_url, debug_dir)
            blocks = _find_subscription_blocks(page)
            if not blocks:
                log.error("No subscription cards found on profile page")
                _save_screenshot(page, debug_dir, "99_no_blocks")
                raise RuntimeError("Profile page DOM didn't match expected structure")

            # Auto-accept any native browser confirm() dialogs (the portal
            # uses one for Regenerate). Must be registered BEFORE clicks.
            page.on("dialog", lambda d: d.accept())

            for i, blk in enumerate(blocks):
                kind = _classify_subscription(blk["name"])
                if not kind:
                    log.info("Row %d: unrecognised name '%s' \u2014 skipping", i, blk["name"][:80])
                    continue
                env_var = SUBSCRIPTION_ENV_MAP[kind]
                log.info("Row %d \u2192 %s (%s)", i, kind, env_var)

                if dry_run:
                    current = _show_and_read_key(blk, "dryrun", debug_dir, page, i)
                    log.info("  current value: %s", _mask(current or ""))
                    if current:
                        new_keys[env_var] = current
                    continue

                _regenerate_primary(blk, debug_dir, page, i)
                new = _show_and_read_key(blk, "regenerate", debug_dir, page, i)
                if not new:
                    log.error("Could not read new key for %s after regenerate", kind)
                    raise RuntimeError(f"Failed to read regenerated key for {kind}")
                log.info("  new value: %s", _mask(new))
                new_keys[env_var] = new
                # Light pause between rows to be polite to the portal
                page.wait_for_timeout(1500)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return new_keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Log in + read current keys without regenerating")
    parser.add_argument("--rotate", action="store_true", help="Actually regenerate Primary keys")
    args = parser.parse_args()

    if not (args.dry_run or args.rotate):
        parser.error("Pass --dry-run or --rotate")

    for env_var in ("NBB_PORTAL_URL", "NBB_PORTAL_USER", "NBB_PORTAL_PASSWORD"):
        if not os.environ.get(env_var):
            log.error("Missing required env: %s", env_var)
            return 2

    new_keys = rotate_keys(dry_run=args.dry_run)

    if not new_keys:
        log.error("No keys captured \u2014 aborting before touching env files")
        return 1

    if args.dry_run:
        log.info("Dry-run complete. Keys read: %s", {k: _mask(v) for k, v in new_keys.items()})
        return 0

    raw = os.environ.get("NBB_ENV_FILES", "/data/.env.production,/data/.env")
    for path in _resolve_env_files(raw):
        _patch_env_file(path, new_keys)

    log.info("Rotation complete. New keys written to %s", raw)
    log.info("Next: restart the backend container with `docker compose up -d --force-recreate backend frontend` (and the staging variant).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
