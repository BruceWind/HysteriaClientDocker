#!/usr/bin/env python3
"""
Periodic Hysteria runner.

Behavior:
 1. Start a single long‑running Hysteria client with an initial config name
    passed from the shell (`-c best_config` from `start.sh`).
 2. Every N seconds, call into `config_tester.test_all_configs` to re-evaluate
    all configs and pick the best one by latency.
 3. If the best config name changes, stop the current Hysteria process and
    start a new one with the new best config.

This keeps exactly one Hysteria client process alive, always using the
currently best-performing config.
"""

import os
import sys
import time
import subprocess
import signal
import threading
import json
from datetime import datetime

from config_tester import (
    test_all_configs,
    print_test_summary,
    test_connectivity,
    resolve_test_urls,
)


def _ts() -> str:
    """Return current timestamp string for logs."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PeriodicRunner:
    """
    Simple periodic best-config runner built on top of `config_tester.py`.
    """

    def __init__(
        self,
        config_dir: str = "/etc/hysteria",
        test_interval: int = 180,
        current_config_file: str = "/tmp/current_config.json",
        main_proxy_port: int = 1080,
    ) -> None:
        self.config_dir = config_dir
        self.test_interval = test_interval  # seconds
        self.current_config_file = current_config_file
        self.main_proxy_port = main_proxy_port

        self.running = True
        self.hysteria_process: subprocess.Popen | None = None
        self.current_config: str | None = None
        self.test_thread: threading.Thread | None = None

        # Reuse the same URL resolution logic as config_tester so env/CLI
        # overrides behave consistently.
        self.test_urls = resolve_test_urls(None)

        # Load last known config (if any)
        self._load_current_config()

        # Signal handlers for clean shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    # ------------------------------------------------------------------ #
    # State persistence
    # ------------------------------------------------------------------ #
    def _load_current_config(self) -> None:
        try:
            if os.path.exists(self.current_config_file):
                with open(self.current_config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.current_config = data.get("config")
                print(f"📋 Loaded previous config from state file: {self.current_config}")
        except Exception as e:  # pylint: disable=broad-except
            print(f"⚠️  Could not load current config state: {e}")
            self.current_config = None

    def _save_current_config(self, config_name: str, latency: float) -> None:
        try:
            data = {
                "config": config_name,
                "latency": float(latency),
                "timestamp": datetime.now().isoformat(),
            }
            with open(self.current_config_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:  # pylint: disable=broad-except
            print(f"⚠️  Could not save current config state: {e}")

    # ------------------------------------------------------------------ #
    # Signal handling
    # ------------------------------------------------------------------ #
    def _signal_handler(self, signum, frame) -> None:  # type: ignore[override]
        del frame  # unused
        print(f"\n🛑 Received signal {signum}, shutting down periodic runner...", flush=True)
        self.running = False
        self.stop_hysteria()
        sys.exit(0)

    # ------------------------------------------------------------------ #
    # Hysteria process management
    # ------------------------------------------------------------------ #
    def _measure_current_latency(self) -> tuple[bool, float, str]:
        """
        Measure latency through the main SOCKS5 proxy of the *currently
        running* Hysteria process.
        """
        if not self.hysteria_process or self.hysteria_process.poll() is not None:
            return False, 0.0, "Hysteria not running"

        success, latency, message = test_connectivity(
            proxy_port=self.main_proxy_port,
            test_urls=self.test_urls,
            timeout=5,
        )
        return success, latency, message

    def _get_saved_latency(self) -> float | None:
        """
        Read the last saved latency from the state file (if present).
        """
        try:
            if not os.path.exists(self.current_config_file):
                return None
            with open(self.current_config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            value = data.get("latency")
            return float(value) if value is not None else None
        except Exception as e:  # pylint: disable=broad-except
            print(f"⚠️  Could not read saved latency: {e}")
            return None

    def stop_hysteria(self) -> None:
        """Stop current Hysteria process if running."""
        if not self.hysteria_process:
            return

        try:
            print(f"[{_ts()}] 🛑 Stopping current Hysteria process...", flush=True)
            self.hysteria_process.terminate()
            self.hysteria_process.wait(timeout=10)
            print(f"[{_ts()}] ✅ Hysteria process stopped", flush=True)
        except subprocess.TimeoutExpired:
            print(f"[{_ts()}] ⚠️  Force killing Hysteria process...", flush=True)
            self.hysteria_process.kill()
            self.hysteria_process.wait()
        except Exception as e:  # pylint: disable=broad-except
            print(f"[{_ts()}] ⚠️  Error stopping Hysteria: {e}", flush=True)
        finally:
            self.hysteria_process = None

    def start_hysteria(self, config_name: str) -> bool:
        """Start a long-lived Hysteria client for `config_name`."""
        config_path = os.path.join(self.config_dir, f"{config_name}.yaml")
        print(f"[{_ts()}] start_hysteria# config_path: {config_path}", flush=True)

        if not os.path.exists(config_path):
            print(f"[{_ts()}] ❌ Config file not found: {config_path}", flush=True)
            return False

        try:
            print(f"[{_ts()}] 🚀 Starting Hysteria with config: {config_name}", flush=True)
            self.hysteria_process = subprocess.Popen(
                ["hysteria", "-c", config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Small delay to verify it didn't die immediately
            time.sleep(2)

            if self.hysteria_process.poll() is None:
                self.current_config = config_name
                print(f"[{_ts()}] ✅ Hysteria started successfully with {config_name}", flush=True)

                # Immediately measure and persist current latency for later
                # comparison in the periodic worker.
                ok, latency, msg = self._measure_current_latency()
                if ok:
                    print(
                        f"[{_ts()}] 📈 Initial latency for {config_name}: "
                        f"{latency:.1f}ms ({msg})",
                        flush=True,
                    )
                    # Persist this latency so future periodic rounds can
                    # compare against it without keeping extra in-memory
                    # state.
                    self._save_current_config(config_name, latency)
                else:
                    print(
                        f"[{_ts()}] ⚠️  Could not measure initial latency for {config_name}: {msg}",
                        flush=True,
                    )
                return True

            print(f"[{_ts()}] ❌ Hysteria failed to start with {config_name}", flush=True)
            self.hysteria_process = None
            return False
        except Exception as e:  # pylint: disable=broad-except
            print(f"[{_ts()}] ❌ Error starting Hysteria: {e}", flush=True)
            self.hysteria_process = None
            return False

    # ------------------------------------------------------------------ #
    # Best-config selection using config_tester
    # ------------------------------------------------------------------ #
    def find_best_config(self) -> dict | None:
        """
        Use `config_tester.test_all_configs` to determine the best config.

        Returns a result dict like:
        {
            'config': 'config-name',
            'success': True,
            'latency': 123.4,
            'message': '...'
        }
        or None if no working configs are found.
        """
        print(f"\n[{_ts()}] 🔄 Periodic test starting...", flush=True)

        try:
            # Use a fixed base proxy port for tests; test_all_configs will offset per config
            results = test_all_configs(self.config_dir, proxy_port=1081)

            if not results:
                print("❌ No configs available for testing", flush=True)
                return None

            # Reuse summary printer for nice output (we ignore its return value here)
            print_test_summary(results)

            successful = [r for r in results if r.get("success")]
            if not successful:
                print("❌ No working configs found", flush=True)
                return None

            successful.sort(key=lambda r: r["latency"])
            best = successful[0]
            ## print(f"🏆 Best config (periodic): {best['config']} ({best['latency']:.1f}ms)")
            return best
        except Exception as e:  # pylint: disable=broad-except
            print(f"❌ Error during periodic test: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Periodic worker
    # ------------------------------------------------------------------ #
    def _periodic_worker(self) -> None:
        """
        Background thread:
          - sleeps `test_interval`
          - recomputes best config via `config_tester`
          - if name changed, restarts the Hysteria client with new best
        """
        while self.running:
            try:
                time.sleep(self.test_interval)
                if not self.running:
                    break

                # Before we tear anything down, quickly measure latency on the
                # *current* running config via the main proxy port. If the
                # latency has not worsened compared to the cached value, skip
                # this round entirely to avoid unnecessary restarts and keep
                # a smoother user experience.
                previous_config = self.current_config

                if self.hysteria_process and previous_config:
                    ok, new_latency, msg = self._measure_current_latency()
                    old_latency = self._get_saved_latency()
                    if ok and old_latency is not None:
                        print(
                            f"[{_ts()}] 🔍 Latency check before periodic switch: "
                            f"old={old_latency:.1f}ms, new={new_latency:.1f}ms ({msg})",
                            flush=True,
                        )
                        if new_latency < old_latency - 20:
                            # this saving make us cache the best latency after tests.
                            self._save_current_config(previous_config, new_latency)
                        if new_latency <= old_latency + 30:
                            print(
                                f"[{_ts()}] ✅ Latency not worse; skipping re-selection this round.",
                                flush=True,
                            )
                            continue
                    elif not ok:
                        print(
                            f"[{_ts()}] ⚠️  Latency probe failed before periodic switch: {msg}",
                            flush=True,
                        )

                # Stop current Hysteria before running tests to avoid interference
                self.stop_hysteria()

                best = self.find_best_config()
                if not best:
                    print("⚠️  No usable config found in this round.")
                    # If we had a previous config, try to bring it back up
                    if previous_config:
                        print(f"🔁 Restoring previous config: {previous_config}")
                        self.start_hysteria(previous_config)
                    continue

                best_name = best["config"]
                best_latency = best["latency"]

                # Start (or restart) Hysteria with the best config found this round
                if best_name == previous_config:
                    print(f"✅ {best_name} is still the best, restarting Hysteria with it.")
                else:
                    print(f"🔄 Switching to new best config: {best_name}")

                if self.start_hysteria(best_name):
                    print(f"✅ Hysteria running with best config: {best_name}")
                else:
                    print(f"❌ Failed to start best config {best_name}.")
            except Exception as e:  # pylint: disable=broad-except
                print(f"❌ Error in periodic worker: {e}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def start(self, initial_config: str | None = None) -> None:
        """
        Start Hysteria (optionally with a given initial config name from CLI)
        and then start the periodic worker thread.
        """
        # If CLI provided an initial config, prefer that over saved state
        start_config = initial_config or self.current_config

        if start_config:
            if not self.start_hysteria(start_config):
                print(f"❌ Failed to start with initial config: {start_config}", flush=True)
                # Don't exit; the periodic worker might still find a working one later
        else:
            print("ℹ️  No initial config provided and no previous state; will wait for periodic tests.", flush=True)

        # Start periodic testing in the background
        self.test_thread = threading.Thread(target=self._periodic_worker, daemon=True)
        self.test_thread.start()

        print(f"🔄 Periodic testing started (every {self.test_interval} seconds)")

        # Main loop: keep the container alive and restart client if it crashes
        try:
            while self.running:
                if self.hysteria_process and self.hysteria_process.poll() is not None:
                    print("❌ Hysteria process exited unexpectedly.")
                    # Let periodic worker pick a good config; try restarting the same one for now
                    if self.current_config:
                        print(f"🔁 Restarting Hysteria with current config: {self.current_config}")
                        self.start_hysteria(self.current_config)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Received keyboard interrupt, stopping...", flush=True)
        finally:
            self.running = False
            self.stop_hysteria()


def main() -> None:
    import argparse

    # Helpful banner to confirm that this entrypoint is actually running
    print("🚀 boot_with_periordic_tester.py main() starting...", flush=True)

    parser = argparse.ArgumentParser(description="Periodic Hysteria best-config runner")
    parser.add_argument(
        "-d",
        "--dir",
        default="/etc/hysteria",
        help="Config directory path",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=180,
        help="Test interval in seconds (default: 180 = 3 minutes)",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="Initial config name (without .yaml) to start with",
    )

    args = parser.parse_args()

    runner = PeriodicRunner(
        config_dir=args.dir,
        test_interval=args.interval,
    )
    print(f"Initial config from CLI: {args.config}", flush=True)
    # check if args.config is a valid config name, if so throw an error
    if args.config and not os.path.exists(os.path.join(args.dir, f"{args.config}.yaml")):
        print(f"❌ Config file not found: {os.path.join(args.dir, f'{args.config}.yaml')}")
        sys.exit(1)

    print("--------------------------------")
    runner.start(args.config)


if __name__ == "__main__":
    main()
