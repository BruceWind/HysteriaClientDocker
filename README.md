# Hysteria Client Docker

This repository provides a Docker setup for running the Hysteria client. Hysteria is a project designed for secure, high-performance communication.

## Quick Start

To get started with the Hysteria client in Docker, follow these simple steps:

1. **Add your URLs**: 
   `config/urls.txt` is used to add your desired URLs. 
   Note that the current implementation supports only one URL.

2. **Build and Run with Docker**:
   Execute the following command in your terminal:

   ```bash
   docker compose build && docker compose up
   ```

This command will build the necessary Docker images and start the Hysteria client service.


## Exposed Ports

The following ports are exposed for communication:

- **SOCKS Port**: `1080`
- **HTTP Port**: `1089`
## Usage

After the service is up and running, the Hysteria client will be configured based on the URL specified in your `urls.txt` file. You can then interact with the service as needed.

## Contributing

Feel free to contribute to this project by submitting issues, suggesting features, or creating pull requests.

## Acknowledgements

This project utilizes the Hysteria client developed by [apernet](https://github.com/apernet/hysteria). Please refer to their documentation for more details on features and usage.