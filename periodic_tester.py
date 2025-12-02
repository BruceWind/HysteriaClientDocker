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

from config_tester import test_all_configs, print_test_summary


class PeriodicRunner:
    """
    Simple periodic best-config runner built on top of `config_tester.py`.
    """

    def __init__(
        self,
        config_dir: str = "/etc/hysteria",
        test_interval: int = 180,
        current_config_file: str = "/tmp/current_config.json",
    ) -> None:
        self.config_dir = config_dir
        self.test_interval = test_interval  # seconds
        self.current_config_file = current_config_file

        self.running = True
        self.hysteria_process: subprocess.Popen | None = None
        self.current_config: str | None = None
        self.test_thread: threading.Thread | None = None

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
        print(f"\n🛑 Received signal {signum}, shutting down periodic runner...")
        self.running = False
        self.stop_hysteria()
        sys.exit(0)

    # ------------------------------------------------------------------ #
    # Hysteria process management
    # ------------------------------------------------------------------ #
    def stop_hysteria(self) -> None:
        """Stop current Hysteria process if running."""
        if not self.hysteria_process:
            return

        try:
            print("🛑 Stopping current Hysteria process...")
            self.hysteria_process.terminate()
            self.hysteria_process.wait(timeout=10)
            print("✅ Hysteria process stopped")
        except subprocess.TimeoutExpired:
            print("⚠️  Force killing Hysteria process...")
            self.hysteria_process.kill()
            self.hysteria_process.wait()
        except Exception as e:  # pylint: disable=broad-except
            print(f"⚠️  Error stopping Hysteria: {e}")
        finally:
            self.hysteria_process = None

    def start_hysteria(self, config_name: str) -> bool:
        """Start a long-lived Hysteria client for `config_name`."""
        config_path = os.path.join(self.config_dir, f"{config_name}.yaml")
        print(f"start_hysteria# config_path: {config_path}")

        if not os.path.exists(config_path):
            print(f"❌ Config file not found: {config_path}")
            return False

        try:
            print(f"🚀 Starting Hysteria with config: {config_name}")
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
                print(f"✅ Hysteria started successfully with {config_name}")
                return True

            print(f"❌ Hysteria failed to start with {config_name}")
            self.hysteria_process = None
            return False
        except Exception as e:  # pylint: disable=broad-except
            print(f"❌ Error starting Hysteria: {e}")
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
        print(f"\n🔄 Periodic test starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            # Use a fixed base proxy port for tests; test_all_configs will offset per config
            results = test_all_configs(self.config_dir, proxy_port=1081)

            if not results:
                print("❌ No configs available for testing")
                return None

            # Reuse summary printer for nice output (we ignore its return value here)
            print_test_summary(results)

            successful = [r for r in results if r.get("success")]
            if not successful:
                print("❌ No working configs found")
                return None

            successful.sort(key=lambda r: r["latency"])
            best = successful[0]
            print(f"🏆 Best config (periodic): {best['config']} ({best['latency']:.1f}ms)")
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

                best = self.find_best_config()
                if not best:
                    print("⚠️  No usable config found in this round, keeping current config.")
                    continue

                best_name = best["config"]
                best_latency = best["latency"]

                # If this is the same config as we're already running, do nothing
                if best_name == self.current_config:
                    print(f"✅ Current config {self.current_config} is still the best.")
                    continue

                print(f"🔄 Switching to new best config: {best_name}")
                self.stop_hysteria()

                if self.start_hysteria(best_name):
                    self._save_current_config(best_name, best_latency)
                    print(f"✅ Successfully switched to {best_name}")
                else:
                    print(f"❌ Failed to start new best config {best_name}.")
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
                print(f"❌ Failed to start with initial config: {start_config}")
                # Don't exit; the periodic worker might still find a working one later
        else:
            print("ℹ️  No initial config provided and no previous state; will wait for periodic tests.")

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
            print("\n🛑 Received keyboard interrupt, stopping...")
        finally:
            self.running = False
            self.stop_hysteria()


def main() -> None:
    import argparse

    # Helpful banner to confirm that this entrypoint is actually running
    print("🚀 periodic_tester.py main() starting...", flush=True)

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
    print("--------------------------------")
    runner.start(args.config)


if __name__ == "__main__":
    main()
