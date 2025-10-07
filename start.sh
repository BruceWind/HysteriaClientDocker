#!/bin/sh

# Start script for Hysteria Client Docker container

set -e

echo "Starting Hysteria Client..."

# Check if hysteria binary exists
if [ ! -f "/usr/local/bin/hysteria" ]; then
    echo "Error: Hysteria binary not found at /usr/local/bin/hysteria"
    exit 1
fi

# Wait for any initialization
sleep 2

# Display Hysteria version
echo "Hysteria version:"
hysteria version


rm -f /etc/hysteria/*.yaml

# Check if urls.txt file exists and process URLs
if [ -f "/etc/hysteria/urls.txt" ]; then
    echo "🔗 Processing Hysteria URLs from urls.txt..."
    python3 /app/url_parser.py --batch
    
    if [ $? -eq 0 ]; then
        echo "✅ Configurations generated successfully"
        echo "📁 Generated config files in /etc/hysteria/"
        ls -la /etc/hysteria/*.yaml 2>/dev/null || echo "No YAML files found"
        
        # Count config files
        config_count=$(ls /etc/hysteria/*.yaml 2>/dev/null | wc -l)
        
        if [ "$config_count" -gt 1 ]; then
            echo ""
            echo "🔍 Multiple configs detected ($config_count files). Running connectivity tests..."
            echo "This may take a few minutes..."
            python3 /app/config_tester.py
            
            if [ $? -eq 0 ]; then
                echo ""
                echo "🚀 Automatically starting Hysteria with the best performing config..."
                
                # Get the best config
                best_config=$(python3 /app/config_tester.py --return-best)
                
                if [ $? -eq 0 ] && [ -n "$best_config" ]; then
                    echo "✅ Using best config: $best_config"
                    echo "🔄 Starting periodic testing (every 5 minutes)..."
                    exec python3 /app/periodic_tester.py -c "$best_config"
                else
                    echo "❌ Failed to determine best config. Available configs:"
                    ls -la /etc/hysteria/*.yaml 2>/dev/null || echo "No config files available"
                    echo ""
                    echo "📋 To run Hysteria with a specific config:"
                    echo "   docker exec -it hysteria-client hysteria -c /etc/hysteria/your-config.yaml"
                fi
            else
                echo ""
                echo "⚠️  All tests failed. Check the output above for details."
                echo "Available configs:"
                ls -la /etc/hysteria/*.yaml 2>/dev/null || echo "No config files available"
            fi
        else
            # 获取所有 *.yaml 文件并执行 hysteria 程序
            for yaml_file in /etc/hysteria/*.yaml; do
            # 检查是否存在符合条件的文件
                if [ -f "$yaml_file" ]; then
                    echo "exec: $yaml_file"
                    # 在此处调用 hysteria 程序，示例命令如下（请根据实际情况调整）
                    hysteria -c "$yaml_file"
                else
                    echo "No config files available"
                fi
            done
        fi
    else
        echo "❌ Failed to process URLs from urls.txt"
        echo "📝 Please check your URLs file format"
        exit 1
    fi
else
    echo "📝 No urls.txt file found in /etc/hysteria/"
    echo "💡 To use URL parsing, create config/urls.txt with your Hysteria URLs"
    echo "   Example:"
    echo "   hysteria2://password@server:port?insecure=1&sni=example.com#Server-Name"
    echo ""
    echo "📋 Available commands:"
    echo "   - Process URLs file: python3 /app/url_parser.py --batch"
    echo "   - Generate single config: python3 /app/url_parser.py 'your-url'"
    echo "   - Test all configs: python3 /app/config_tester.py"
    echo "   - Start periodic testing: python3 /app/periodic_tester.py -c config-name"
    echo "   - Run with config: hysteria -c /etc/hysteria/config.yaml"
    echo "   - Show version: hysteria version"
    
    # Keep container running for manual operations
    tail -f /dev/null
fi
