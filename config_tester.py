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
            'listen': f'127.0.0.1:{proxy_port}'
        }
        
        # Write test config
        with open(test_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        return True
    except Exception as e:
        print(f"❌ Error creating test config: {str(e)}", file=sys.stderr)
        return False


def test_connectivity(proxy_port=1080, test_url="https://www.google.com/generate_204", timeout=10):
    """
    Test connectivity through SOCKS5 proxy and measure latency
    """
    proxies = {
        'http': f'socks5://127.0.0.1:{proxy_port}',
        'https': f'socks5://127.0.0.1:{proxy_port}'
    }
    
    try:
        start_time = time.time()
        response = requests.get(test_url, proxies=proxies, timeout=timeout)
        end_time = time.time()
        
        latency = (end_time - start_time) * 1000  # Convert to milliseconds
        
        if response.status_code == 204:
            return True, latency, "Success"
        else:
            return False, latency, f"HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, timeout * 1000, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, 0, "Connection Error"
    except Exception as e:
        return False, 0, str(e)


def run_hysteria_test(config_path, proxy_port=1080, test_url="https://www.google.com/generate_204", test_duration=15):
    """
    Run Hysteria with a config and test connectivity
    """
    config_name = os.path.basename(config_path).replace('.yaml', '')
    test_config_path = config_path.replace('.yaml', '_test.yaml')
    
    print(f"🧪 Testing config: {config_name}")
    
    # Create test config with SOCKS5 proxy
    if not create_test_config(config_path, test_config_path, proxy_port):
        return False, 0, "Config creation failed"
    
    # Start Hysteria process
    try:
        process = subprocess.Popen(
            ['/usr/local/bin/hysteria', '-c', test_config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait a bit for Hysteria to start
        time.sleep(3)
        
        # Test connectivity
        success, latency, message = test_connectivity(proxy_port, test_url)
        
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


def test_all_configs(config_dir="/etc/hysteria", proxy_port=1080, test_url="https://www.google.com/generate_204"):
    """
    Test all config files and return results
    """
    config_files = find_config_files(config_dir)
    
    if not config_files:
        print("❌ No config files found")
        return []
    
    print(f"🔍 Found {len(config_files)} config file(s)")
    print(f"🌐 Testing connectivity to: {test_url}")
    print(f"🔌 Using SOCKS5 proxy on port: {proxy_port}")
    print("-" * 50)
    
    results = []
    
    for config_file in config_files:
        success, latency, message = run_hysteria_test(config_file, proxy_port, test_url)
        
        config_name = os.path.basename(config_file).replace('.yaml', '')
        results.append({
            'config': config_name,
            'success': success,
            'latency': latency,
            'message': message
        })
        
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
        print(f"💡 To use: /usr/local/bin/hysteria -c /etc/hysteria/{best['config']}.yaml")
        return best['config']
    
    return None


def main():
    parser = argparse.ArgumentParser(description='Test Hysteria config files')
    parser.add_argument('-d', '--dir', default='/etc/hysteria', 
                       help='Config directory path')
    parser.add_argument('-p', '--port', type=int, default=1080, 
                       help='SOCKS5 proxy port')
    parser.add_argument('-u', '--url', default='https://www.google.com/generate_204', 
                       help='Test URL')
    parser.add_argument('--return-best', action='store_true',
                       help='Return the best config name instead of printing summary')
    
    args = parser.parse_args()
    
    # Test all configs
    results = test_all_configs(args.dir, args.port, args.url)
    
    # Get best config
    best_config = print_test_summary(results)
    
    if args.return_best:
        # Return best config for shell script use
        if best_config:
            print(best_config)  # This will be captured by shell
            sys.exit(0)
        else:
            sys.exit(1)
    
    # Exit with error if no configs succeeded
    if results and not any(r['success'] for r in results):
        sys.exit(1)


if __name__ == '__main__':
    import argparse
    main()
