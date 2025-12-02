#!/usr/bin/env python3
"""
Periodic Hysteria Config Tester
Runs config tests every 5 minutes and switches to better configs
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
import glob


class PeriodicTester:
    def __init__(self, config_dir="/etc/hysteria", test_interval=180, current_config_file="/tmp/current_config.json"):
        self.config_dir = config_dir
        self.test_interval = test_interval  # default 3 minutes = 180 seconds
        self.current_config_file = current_config_file
        self.running = True
        self.hysteria_process = None
        self.current_config = None
        self.test_thread = None
        
        # Load current config if exists
        self.load_current_config()
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n🛑 Received signal {signum}, shutting down periodic tester...")
        self.running = False
        self.stop_hysteria()
        sys.exit(0)
    
    def load_current_config(self):
        """Load current active config from file"""
        try:
            if os.path.exists(self.current_config_file):
                with open(self.current_config_file, 'r') as f:
                    data = json.load(f)
                    self.current_config = data.get('config')
                    print(f"📋 Loaded current config: {self.current_config}")
        except Exception as e:
            print(f"⚠️  Could not load current config: {e}")
            self.current_config = None
    
    def save_current_config(self, config_name, latency):
        """Save current active config to file"""
        try:
            data = {
                'config': config_name,
                'latency': latency,
                'timestamp': datetime.now().isoformat()
            }
            with open(self.current_config_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"⚠️  Could not save current config: {e}")
    
    def stop_hysteria(self):
        """Stop current Hysteria process"""
        if self.hysteria_process:
            try:
                print("🛑 Stopping current Hysteria process...")
                self.hysteria_process.terminate()
                self.hysteria_process.wait(timeout=10)
                print("✅ Hysteria process stopped")
            except subprocess.TimeoutExpired:
                print("⚠️  Force killing Hysteria process...")
                self.hysteria_process.kill()
                self.hysteria_process.wait()
            except Exception as e:
                print(f"⚠️  Error stopping Hysteria: {e}")
            finally:
                self.hysteria_process = None
    
    def start_hysteria(self, config_name):
        """Start Hysteria with specified config"""
        config_path = os.path.join(self.config_dir, f"{config_name}.yaml")
        
        if not os.path.exists(config_path):
            print(f"❌ Config file not found: {config_path}")
            return False
        
        try:
            print(f"🚀 Starting Hysteria with config: {config_name}")
            self.hysteria_process = subprocess.Popen(
                ['hysteria', '-c', config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait a moment to ensure it started successfully
            time.sleep(2)
            
            if self.hysteria_process.poll() is None:
                print(f"✅ Hysteria started successfully with {config_name}")
                self.current_config = config_name
                return True
            else:
                print(f"❌ Hysteria failed to start with {config_name}")
                self.hysteria_process = None
                return False
                
        except Exception as e:
            print(f"❌ Error starting Hysteria: {e}")
            return False
    
    def get_current_latency(self, config_name):
        """Get current latency for a specific config"""
        try:
            # Quick test of current config
            from config_tester import run_hysteria_test
            success, latency, message = run_hysteria_test(
                os.path.join(self.config_dir, f"{config_name}.yaml"),
                proxy_port=1081,  # Use different port to avoid conflicts
                test_duration=10
            )
            return latency if success else float('inf')
        except Exception as e:
            print(f"⚠️  Error testing current config: {e}")
            return float('inf')
    
    def find_best_config(self):
        """Find the best performing config"""
        print(f"\n🔄 Periodic test starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Test all configs
            results = test_all_configs(self.config_dir, proxy_port=1081)
            
            if not results:
                print("❌ No configs available for testing")
                return None
            
            # Find best successful config
            successful_configs = [r for r in results if r['success']]
            
            if not successful_configs:
                print("❌ No working configs found")
                return None
            
            # Sort by latency and get the best one
            successful_configs.sort(key=lambda x: x['latency'])
            best_config = successful_configs[0]
            
            print(f"🏆 Best config: {best_config['config']} ({best_config['latency']:.1f}ms)")
            
            return best_config
            
        except Exception as e:
            print(f"❌ Error during periodic test: {e}")
            return None
    
    def should_switch_config(self, new_best_config):
        """Determine if we should switch to a new config"""
        if not self.current_config:
            return True
        
        # Get current config latency
        current_latency = self.get_current_latency(self.current_config)
        
        # If current config is failing, switch
        if current_latency == float('inf'):
            print(f"❌ Current config {self.current_config} is not working, switching...")
            return True
        
        # If new config is significantly better (20% improvement), switch
        improvement_threshold = 0.8  # 20% improvement
        if new_best_config['latency'] < current_latency * improvement_threshold:
            print(f"📈 New config is {((current_latency - new_best_config['latency']) / current_latency * 100):.1f}% faster, switching...")
            return True
        
        # If new config is the same as current, no need to switch
        if new_best_config['config'] == self.current_config:
            return False
        
        # If new config is only slightly better, switch if it's been a while
        if new_best_config['latency'] < current_latency:
            print(f"📊 New config is {current_latency - new_best_config['latency']:.1f}ms faster, but keeping current config")
        
        return False
    
    def periodic_test_worker(self):
        """Worker thread for periodic testing"""
        while self.running:
            try:
                # Wait for the test interval
                time.sleep(self.test_interval)
                
                if not self.running:
                    break
                
                # Find best config
                best_config = self.find_best_config()
                
                if not best_config:
                    print("⚠️  No working configs found, keeping current config")
                    continue
                
                # Check if we should switch
                if self.should_switch_config(best_config):
                    print(f"🔄 Switching to better config: {best_config['config']}")
                    
                    # Stop current Hysteria
                    self.stop_hysteria()
                    
                    # Start with new config
                    if self.start_hysteria(best_config['config']):
                        self.save_current_config(best_config['config'], best_config['latency'])
                        print(f"✅ Successfully switched to {best_config['config']}")
                    else:
                        print(f"❌ Failed to start with {best_config['config']}, trying to restart with previous config")
                        if self.current_config and self.start_hysteria(self.current_config):
                            print(f"✅ Restarted with previous config: {self.current_config}")
                else:
                    print(f"✅ Current config {self.current_config} is still optimal")
                
            except Exception as e:
                print(f"❌ Error in periodic test worker: {e}")
    
    def start_periodic_testing(self, initial_config=None):
        """Start Hysteria and begin periodic testing"""
        # Start with initial config if provided
        if initial_config:
            if self.start_hysteria(initial_config):
                self.save_current_config(initial_config, 0)
            else:
                print(f"❌ Failed to start with initial config: {initial_config}")
                return False
        
        # Start periodic testing thread
        self.test_thread = threading.Thread(target=self.periodic_test_worker, daemon=True)
        self.test_thread.start()
        
        print(f"🔄 Periodic testing started (every {self.test_interval} seconds)")
        
        # Keep main thread alive
        try:
            while self.running:
                if self.hysteria_process and self.hysteria_process.poll() is not None:
                    print("❌ Hysteria process died, restarting...")
                    if self.current_config:
                        self.start_hysteria(self.current_config)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Received keyboard interrupt")
        finally:
            self.running = False
            self.stop_hysteria()
    
    def run(self, initial_config=None):
        """Main entry point"""
        print("🚀 Starting Hysteria with periodic testing...")
        self.start_periodic_testing(initial_config)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Periodic Hysteria config tester')
    parser.add_argument('-d', '--dir', default='/etc/hysteria', 
                       help='Config directory path')
    parser.add_argument('-i', '--interval', type=int, default=180, 
                       help='Test interval in seconds (default: 180 = 3 minutes)')
    parser.add_argument('-c', '--config', 
                       help='Initial config to start with')
    
    args = parser.parse_args()
    
    tester = PeriodicTester(
        config_dir=args.dir,
        test_interval=args.interval
    )
    
    tester.run(args.config)


if __name__ == '__main__':
    main()
