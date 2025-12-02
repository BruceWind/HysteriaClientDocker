#!/usr/bin/env python3
"""
Hysteria Config Tester
Tests each generated config by running Hysteria and measuring latency
"""

import os
import sys
import time
import subprocess
import glob
import requests
import threading
import signal
from concurrent.futures import ThreadPoolExecutor
import yaml


DEFAULT_TEST_URLS = [
    "https://cp.cloudflare.com/generate_204",
    "https://www.bing.com",
    "https://www.google.com/generate_204",
]


def resolve_test_urls(cli_value=None):
    """
    Decide which test URLs to use.

    Priority:
      1. CLI argument (comma-separated)
      2. HYSTERIA_TEST_URLS env var (comma-separated)
      3. DEFAULT_TEST_URLS
    """
    source = cli_value or os.getenv("HYSTERIA_TEST_URLS")
    if source:
        urls = [u.strip() for u in source.split(",") if u.strip()]
        if urls:
            return urls
    return DEFAULT_TEST_URLS[:]


def find_config_files(config_dir="/etc/hysteria"):
    """Find all YAML config files in the directory"""
    pattern = os.path.join(config_dir, "*.yaml")
    config_files = glob.glob(pattern)
    return [f for f in config_files if os.path.isfile(f)]


def create_test_config(base_config_path, test_config_path, proxy_port=1080):
    """
    Create a test config file with SOCKS5 proxy enabled
    """
    try:
        with open(base_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Add SOCKS5 proxy configuration
        config['socks5'] = {
            'listen': f'0.0.0.0:{proxy_port}'
        }
        
        # Write test config
        with open(test_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        return True
    except Exception as e:
        print(f"❌ Error creating test config: {str(e)}", file=sys.stderr)
        return False


def test_connectivity(proxy_port=1080, test_urls=None, timeout=5):
    """
    Test connectivity through SOCKS5 proxy and measure latency.
    Tries each URL until one succeeds.
    """
    if not test_urls:
        test_urls = DEFAULT_TEST_URLS

    proxies = {
        'http': f'socks5://127.0.0.1:{proxy_port}',
        'https': f'socks5://127.0.0.1:{proxy_port}'
    }
    
    try:
        last_latency = 0
        last_message = "No attempts made"

        for url in test_urls:
            start_time = time.time()
            try:
                print(f"Testing {url} with proxies {proxies}", flush=True)
                response = requests.get(url, proxies=proxies, timeout=timeout)
                
                end_time = time.time()
                latency = (end_time - start_time) * 1000  # Convert to milliseconds
                
                if response.status_code in (200, 204):
                    return True, latency, f"Success via {url}"
                last_latency = latency
                last_message = f"HTTP {response.status_code} via {url}"
            except requests.exceptions.Timeout:
                last_latency = timeout * 1000
                last_message = f"Timeout via {url}"
            except requests.exceptions.ConnectionError:
                last_latency = 0
                last_message = f"Connection Error via {url}"
            except Exception as e:  # pylint: disable=broad-except
                last_latency = 0
                last_message = f"{str(e)} via {url}"
        
        return False, last_latency, last_message
            
    except Exception as e:
        return False, 0, str(e)


def run_hysteria_test(config_path, proxy_port=1080, test_urls=None, test_duration=15):
    """
    Run Hysteria with a config and test connectivity
    """
    config_name = os.path.basename(config_path).replace('.yaml', '')
    test_config_path = config_path.replace('.yaml', '_test.yaml')
    
    
    # Create test config with SOCKS5 proxy
    if not create_test_config(config_path, test_config_path, proxy_port):
        return False, 0, "Config creation failed"
    
    # Start Hysteria process
    try:
        process = subprocess.Popen(
            ['hysteria', '-c', test_config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait a bit for Hysteria to start and become ready
        # We will also allow a couple of connection attempts before
        # giving up, in case the process is a bit slow to come up.
        ready = False
        success = False
        latency = 0
        message = "Not started"

        start_time = time.time()
        while time.time() - start_time < test_duration:
            # If the process died early, bail out
            if process.poll() is not None:
                message = "Hysteria process exited prematurely"
                break

            # Try a connectivity test
            success, latency, message = test_connectivity(proxy_port, test_urls, timeout=5)
            if success:
                ready = True
                break

            # Small backoff before next attempt
            time.sleep(2)
        
        # Stop Hysteria process
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        
        # Clean up test config
        try:
            os.remove(test_config_path)
        except:
            pass
        
        return success, latency, message
        
    except Exception as e:
        return False, 0, f"Process error: {str(e)}"


def test_all_configs(config_dir="/etc/hysteria", proxy_port=1080, test_urls=None, quiet=False):
    """
    Test all config files and return results
    """
    config_files = find_config_files(config_dir)
    
    if not config_files:
        if not quiet:
            print("❌ No config files found", flush=True)
        return []
    
    if not quiet:
        print(f"🔍 Found {len(config_files)} config file(s)")
    working_test_urls = test_urls or DEFAULT_TEST_URLS
    if not quiet:
        print(f"🌐 Testing connectivity to: {', '.join(working_test_urls)}")
        print(f"🔌 Using SOCKS5 proxy on port: {proxy_port}")
        print("-" * 50)
    
    results = []
    
    for idx, config_file in enumerate(config_files):
        # Use a unique SOCKS5 port per config to avoid any chance of
        # port binding conflicts between tests.
        current_port = proxy_port + idx
        success, latency, message = run_hysteria_test(config_file, current_port, working_test_urls)
        
        config_name = os.path.basename(config_file).replace('.yaml', '')
        results.append({
            'config': config_name,
            'success': success,
            'latency': latency,
            'message': message
        })
        
        if not quiet:
            if success:
                print(f"✅ {config_name}: {latency:.1f}ms - {message}")
            else:
                print(f"❌ {config_name}: {message}")
        
        # Small delay between tests
        time.sleep(2)
    
    return results


def print_test_summary(results):
    """
    Print a summary of test results and return the best config
    """
    if not results:
        return None
    
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    
    successful_configs = [r for r in results if r['success']]
    failed_configs = [r for r in results if not r['success']]
    
    if successful_configs:
        print(f"✅ Successful: {len(successful_configs)}/{len(results)}")
        # Sort by latency
        successful_configs.sort(key=lambda x: x['latency'])
        for i, result in enumerate(successful_configs, 1):
            print(f"   {i}. {result['config']}: {result['latency']:.1f}ms")
    else:
        print("❌ No successful connections")
        return None
    
    if failed_configs:
        print(f"\n❌ Failed: {len(failed_configs)}/{len(results)}")
        for result in failed_configs:
            print(f"   - {result['config']}: {result['message']}")
    
    if successful_configs:
        best = successful_configs[0]
        print(f"\n🏆 Best config: {best['config']} ({best['latency']:.1f}ms)")
        ## print(f"💡 To use: hysteria -c /etc/hysteria/{best['config']}.yaml")
        return best['config']
    
    return None


def main():
    parser = argparse.ArgumentParser(description='Test Hysteria config files')
    parser.add_argument('-d', '--dir', default='/etc/hysteria', 
                       help='Config directory path')
    parser.add_argument('-p', '--port', type=int, default=1080, 
                       help='SOCKS5 proxy port')
    parser.add_argument('-u', '--url', default=None,
                       help='Test URL(s). Comma-separated to provide multiple options.')
    parser.add_argument('--return-best', action='store_true',
                       help='Return the best config name instead of printing summary')
    
    args = parser.parse_args()
    
    test_urls = resolve_test_urls(args.url)

    # If caller only wants the best config name, run in quiet mode and
    # print *only* that name to stdout so shell command substitution works.
    if args.return_best:
        results = test_all_configs(args.dir, args.port, test_urls, quiet=True)
        if not results:
            sys.exit(1)

        successful = [r for r in results if r['success']]
        if not successful:
            sys.exit(1)

        successful.sort(key=lambda x: x['latency'])
        best = successful[0]['config']
        print(best) # this line make shell read this reuslt.
        sys.exit(0)

    # Normal mode: run with full output and summary
    results = test_all_configs(args.dir, args.port, test_urls, quiet=False)
    
    # Get best config and print user-friendly summary
    best_config = print_test_summary(results)
    
    # Exit with error if no configs succeeded
    if results and not any(r['success'] for r in results):
        sys.exit(1)


if __name__ == '__main__':
    import argparse
    main()
