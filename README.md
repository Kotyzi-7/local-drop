# Local Drop

A dependency-free LAN file sharing server. Send files directly between devices on your local network.

## Features

- **Zero dependencies** — runs with just Python's standard library
- **Modern UI** — dark-themed, responsive web interface
- **Drag & drop** — upload files by dragging them onto the browser
- **Multi-file upload** — share multiple files at once
- **Auto-detection** — automatically finds your local IP address
- **Threaded server** — handles concurrent uploads and downloads
- **File management** — download and delete shared files from the browser

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/local-drop.git
   cd local-drop
   ```

2. Run the server:
   ```bash
   python local_share.py
   ```

3. Open the displayed URL (e.g., `http://192.168.1.100:8080`) in any browser on your local network.

4. Start sharing files!

## Usage

- **Upload**: Drag files onto the drop zone or click to select files
- **Download**: Click the "Download" button next to any file
- **Delete**: Click the "Delete" button to remove a shared file

## Configuration

Edit the constants at the top of `local_share.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server port |
| `MAX_UPLOAD_BYTES` | `512 MB` | Maximum upload file size |

## Requirements

- Python 3.10 or higher

## License

MIT License — see [LICENSE](LICENSE) for details.