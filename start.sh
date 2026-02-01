#!/bin/sh

# Start script for Hysteria Client Docker container

set -e

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

CONFIG_DIR="/etc/hysteria"
APP_CONFIG_DIR="/app/config"

# This interval should be greater than 300 seconds, otherwise connections may drop too quickly.
TEST_INTERVAL="${HYSTERIA_TEST_INTERVAL:-300}"

# Debug: Show URL environment variables
echo "🔍 Checking for URL environment variables..."
env | grep -E "^URL[0-9]+" || echo "   No URL1, URL2, ... variables found in environment"

# Copy urls.txt from mounted volume to /etc/hysteria/ if it exists
if [ -f "${APP_CONFIG_DIR}/urls.txt" ]; then
    echo "📄 Found urls.txt in ${APP_CONFIG_DIR}/, copying to ${CONFIG_DIR}/"
    cp "${APP_CONFIG_DIR}/urls.txt" "${CONFIG_DIR}/urls.txt"
fi

# Check if URL1 is set (handles both empty and unset cases)
URL1_SET=$(env | grep -c "^URL1=" || true)

# Check if urls.txt file exists OR if URL1 environment variable is set
if [ -f "${CONFIG_DIR}/urls.txt" ] || [ "$URL1_SET" -gt 0 ]; then
    echo "🔗 Processing Hysteria URLs..."
    if python3 /app/url_parser.py --batch; then
        echo "✅ Configurations generated successfully"
        echo "📁 Generated config files in ${CONFIG_DIR}/"
        ls -la ${CONFIG_DIR}/*.yaml 2>/dev/null || echo "No YAML files found"
        
        config_files=$(ls ${CONFIG_DIR}/*.yaml 2>/dev/null || true)
        config_count=$(echo "$config_files" | grep -c ".yaml" || true)


        # no urls.
        if [ "$config_count" -eq 0 ]; then
            echo "❌ No YAML configs were generated. Please check urls.txt."
            exit 1
        fi

        best_config=""

        if [ "$config_count" -gt 1 ]; then
            echo ""
            echo "🔍 Multiple configs detected ($config_count files). Running connectivity tests..."
            echo "This may take a few minutes..."
            if python3 /app/config_tester.py; then
                echo ""
                echo "🚀 Automatically selecting the best performing config..."
                best_config=$(python3 /app/config_tester.py --return-best || true)

                if [ -n "$best_config" ]; then
                    first_yaml=$(echo "$config_files" | tail -n 1) ## get last line
                    echo "Fallback YAML file (last in list): $first_yaml"
                    best_config=$(basename "$first_yaml") # 获取最后一个yaml文件的名称
                    best_config="${best_config%.yaml}"
                    # echo "ℹ️  Using fallback config: $best_config"
                fi

                echo ""
                echo "🛠️  Proxy ports exposed inside the container:"
                echo "   • SOCKS5 : 0.0.0.0:1080"
                echo "   • HTTP   : 0.0.0.0:1089"
                echo ""
                echo "🔁 Starting periodic tester every ${TEST_INTERVAL} seconds..."
                exec python3 /app/boot_with_periordic_tester.py -c "$best_config" -i "$TEST_INTERVAL"

            else
                echo ""
                echo "⚠️  Automatic tests failed. Falling back to the first config."
            fi
        else
            echo ""
            echo "🔍 Single config detected ($config_count files). No connectivity tests..."
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
    echo "📝 No urls.txt file found and no URL environment variables set"
    echo "💡 Option 1: Create config/urls.txt with your Hysteria URLs"
    echo "💡 Option 2: Set environment variables URL1, URL2, URL3, ..."
    echo "   Example URL:"
    echo "   hysteria2://password@server:port?insecure=1&sni=example.com#Server-Name"
    echo ""
    echo "📋 Available commands:"
    echo "   - Process URLs file: python3 /app/url_parser.py --batch"
    echo "   - Generate single config: python3 /app/url_parser.py 'your-url'"
    echo "   - Test all configs: python3 /app/config_tester.py"
    echo "   - Start periodic testing: python3 /app/boot_with_periordic_tester.py -c config-name"
    echo "   - Run with config: hysteria -c /etc/hysteria/config.yaml"
    echo "   - Show version: hysteria version"
    
    # Keep container running for manual operations
    tail -f /dev/null
fi
