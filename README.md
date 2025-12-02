## Hysteria Client Docker

**Languages**: English | [中文说明](README_zh.md)

This repository provides a Docker setup for running the Hysteria client. Hysteria is a project designed for secure, high-performance communication.

## Quick Start

To get started with the Hysteria client in Docker, follow these simple steps:

1. **Add your URLs**: 
   Add one or more Hysteria URLs to `config/urls.txt`. The container
   will parse every valid line and generate matching config files automatically.

2. **Build and Run with Docker**:
   Execute the following command in your terminal:

   ```bash
   docker compose build && docker compose up -d
   ```

This command will build the necessary Docker images and start the Hysteria client service.

On startup the container:

- parses every URL in `config/urls.txt` and generates YAML configs;
- tests each config on an auxiliary SOCKS port (so that the public `1080/1089`
  ports stay free) and picks the fastest working option; and
- launches `boot_with_periordic_tester.py`, which keeps the selected config running on
  `0.0.0.0:1080` (SOCKS5) and `0.0.0.0:1089` (HTTP) while re-testing every
  3 minutes on background ports to switch automatically when a better link
  appears.

### Notes about periodic testing

- **Single URL / single config**:  
  If `config/urls.txt` effectively results in just one working config, the
  program will simply use that config to establish the tunnel and will **not
  enter the periodic "find best config" loop**.

- **Short proxy pause when current proxy gets worse**:  
  If the cached latency for the current proxy becomes noticeably worse, the
  periodic tester may trigger a full re-evaluation round: the main Hysteria
  process is briefly stopped while test instances are started on auxiliary
  ports. In this case the main proxy (`1080/1089`) can stop accepting traffic
  for roughly **10 seconds** during that window, while it looks for a better
  config.


## Exposed Ports

The following ports are exposed for communication:

- **SOCKS Port**: `1080`
- **HTTP Port**: `1089`
## Environment

- `HYSTERIA_TEST_INTERVAL` (seconds, default `180`): how often the periodic
  tester reruns connectivity checks in the background while clients use the
  main proxy ports.
- `HYSTERIA_TEST_URLS` (comma separated): override the default list of
  probe endpoints (`https://cp.cloudflare.com/generate_204`,
  `https://www.bing.com`, `https://www.google.com/generate_204`) used during
  connectivity tests. This is useful if some sites are blocked in your region.

## Usage

After the service is up and running, point your devices at `localhost:1080`
(SOCKS5) or `localhost:1089` (HTTP) to use the selected Hysteria tunnel.

## Contributing

Feel free to contribute to this project by submitting issues, suggesting features, or creating pull requests.

## Acknowledgements

This project utilizes the Hysteria client developed by [apernet](https://github.com/apernet/hysteria). Please refer to their documentation for more details on features and usage.