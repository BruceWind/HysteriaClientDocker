#!/usr/bin/env python3
"""
Hysteria URL Parser
Parses hysteria2:// URLs and generates config.yaml files
"""

import os
import sys
import yaml
from urllib.parse import urlparse, parse_qs, unquote
import argparse


def parse_hysteria_url(url):
    """
    Parse a hysteria2:// URL and extract configuration parameters
    
    Example URLs:
    hysteria2://57903c8f@v5.xxxx.top:57022?insecure=1&mport=57022&sni=www.bing.com#V5-抗丢包
    hysteria2://d4aa6c84@v3.xxx.top:11092?insecure=1&mport=11092,20000-40000&sni=www.bing.com#V3-抗丢包
    hysteria2://d4aa6c84@11.11.11.11:11092,20000-40000/?insecure=1&sni=www.bing.com#V3-抗丢包
    """
    try:
        # Parse the URL
        parsed = urlparse(url)
        
        if parsed.scheme != 'hysteria2':
            raise ValueError(f"Unsupported scheme: {parsed.scheme}. Expected 'hysteria2'")
        
        # Extract authentication (password)
        auth = parsed.username
        if not auth:
            raise ValueError("Missing authentication in URL")
        
        # Extract query parameters
        query_params = parse_qs(parsed.query)
        
        # Extract name (fragment)
        name = unquote(parsed.fragment) if parsed.fragment else "Hysteria Client"
        
        # Extract server host and port from netloc
        # Handle cases where port might contain ranges like "11092,20000-40000"
        netloc = parsed.netloc
        # Remove auth part if present
        if '@' in netloc:
            netloc = netloc.split('@')[1]
        
        # Split host and port (port may contain comma-separated ranges)
        if ':' in netloc:
            host, port_part = netloc.rsplit(':', 1)
            # port_part might be "11092,20000-40000" or just "11092"
        else:
            host = netloc
            port_part = None
        
        # Build server string - prioritize mport query parameter, then port from URL
        if 'mport' in query_params:
            mport_value = query_params['mport'][0]
            # mport can contain port ranges like "11092,20000-40000"
            server = f"{host}:{mport_value}"
        elif port_part:
            # Use port from URL (may contain port ranges)
            server = f"{host}:{port_part}"
        else:
            # Default to 443 if no port specified
            server = f"{host}:443"
        
        # Build configuration
        config = {
            'server': server,
            'auth': auth,
            'name': name
        }
        
        # Parse TLS settings
        tls_config = {}
        
        if 'insecure' in query_params:
            insecure = query_params['insecure'][0].lower()
            tls_config['insecure'] = insecure in ['1', 'true', 'yes']
        
        if 'sni' in query_params:
            tls_config['sni'] = query_params['sni'][0]
        
        if tls_config:
            config['tls'] = tls_config
        
        # Parse bandwidth settings (if provided)
        if 'up' in query_params:
            config['bandwidth'] = {'up': query_params['up'][0]}
            if 'down' in query_params:
                config['bandwidth']['down'] = query_params['down'][0]
        
        # Parse proxy settings
        if 'socks5' in query_params:
            config['socks5'] = {'listen': query_params['socks5'][0]}
        else:
            # Add default SOCKS5 proxy on port 1080
            config['socks5'] = {'listen': '0.0.0.0:1080'}
        
        if 'http' in query_params:
            config['http'] = {'listen': query_params['http'][0]}
        else:
            # Add default HTTP proxy on port 1089
            config['http'] = {'listen': '0.0.0.0:1089'}
        
        return config
        
    except Exception as e:
        raise ValueError(f"Failed to parse URL: {str(e)}")


def generate_config_file(url, output_path="/etc/hysteria/config.yaml"):
    """
    Parse URL and generate config.yaml file
    """
    try:
        # Parse the URL
        config = parse_hysteria_url(url)
        
        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Write config file
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        print(f"✅ Configuration generated successfully: {output_path}")
        print(f"📝 Server: {config['server']}")
        print(f"🔐 Auth: {config['auth']}")
        print(f"🏷️  Name: {config.get('name', 'N/A')}")
        
        if 'tls' in config:
            print(f"🔒 TLS: {config['tls']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error generating config: {str(e)}", file=sys.stderr)
        return False


def process_urls_file(urls_file_path="/etc/hysteria/urls.txt", output_dir="/etc/hysteria"):
    """
    Process multiple URLs from a text file and generate config files
    """
    if not os.path.exists(urls_file_path):
        print(f"❌ URLs file not found: {urls_file_path}")
        return False
    
    try:
        with open(urls_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        config_count = 0
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            try:
                # Parse the URL
                config = parse_hysteria_url(line)
                
                # Generate filename from config name or use line number
                config_name = config.get('name', f'config_{line_num}')
                # Clean filename (remove special characters)
                safe_name = ''.join(c for c in config_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name.replace(' ', '_')
                
                output_file = os.path.join(output_dir, f'{safe_name}.yaml')
                
                # Write config file
                with open(output_file, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                
                print(f"✅ Config {config_count + 1}: {output_file}")
                print(f"   📝 Server: {config['server']}")
                print(f"   🏷️  Name: {config.get('name', 'N/A')}")
                
                config_count += 1
                
            except Exception as e:
                print(f"❌ Error processing line {line_num}: {str(e)}", file=sys.stderr)
                print(f"   URL: {line}", file=sys.stderr)
                continue
        
        if config_count > 0:
            print(f"\n🎉 Successfully generated {config_count} config file(s)")
            return True
        else:
            print("⚠️  No valid URLs found in file")
            return False
            
    except Exception as e:
        print(f"❌ Error reading URLs file: {str(e)}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description='Parse Hysteria URL(s) and generate config.yaml')
    parser.add_argument('url', nargs='?', help='Single Hysteria URL to parse')
    parser.add_argument('-f', '--file', default='/etc/hysteria/urls.txt', 
                       help='File containing URLs (one per line)')
    parser.add_argument('-o', '--output', default='/etc/hysteria/config.yaml', 
                       help='Output config file path (for single URL)')
    parser.add_argument('--batch', action='store_true', 
                       help='Process URLs from file instead of single URL')
    
    args = parser.parse_args()
    
    if args.batch or not args.url:
        # Process URLs from file
        success = process_urls_file(args.file)
    else:
        # Process single URL
        success = generate_config_file(args.url, args.output)
    
    if not success:
        sys.exit(1)


if __name__ == '__main__':
    main()
