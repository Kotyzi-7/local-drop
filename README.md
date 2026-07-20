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
- **Image preview** — preview images directly in the browser
- **File type icons** — visual icons for different file types
- **Copy link** — copy download links to clipboard with one click
- **Upload speed** — real-time upload speed indicator
- **QR code** — scan to connect from mobile devices
- **Password protection** — optional password to restrict access
- **Auto-expire** — automatically remove old files after a set time
- **Structured logging** — timestamped logs for monitoring

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/Kotyzi-7/local-drop.git
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
- **Copy Link**: Click "Copy Link" to get a shareable download URL
- **Preview**: Click "Preview" on images to view them full-screen
- **Delete**: Click the "Delete" button to remove a shared file
- **Mobile**: Scan the QR code at the bottom of the page to open on another device

## Configuration

Edit the constants at the top of `local_share.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server port |
| `MAX_UPLOAD_BYTES` | `512 MB` | Maximum upload file size |
| `PASSWORD` | `""` (disabled) | Set a password to protect the server |
| `FILE_EXPIRY_HOURS` | `0` (disabled) | Auto-delete files older than N hours |

### Password Protection

Set the `PASSWORD` constant to enable authentication:

```python
PASSWORD = "my-secret-password"
```

Users will be prompted to enter the password before accessing the server.

### Auto-Expire Files

Set `FILE_EXPIRY_HOURS` to automatically clean up old files:

```python
FILE_EXPIRY_HOURS = 24  # Remove files older than 24 hours
```

## Installation

Install via pip for a global `local-drop` command:

```bash
pip install .
```

Or run directly without installing:

```bash
python local_share.py
```

## Running Tests

```bash
python -m pytest tests/
```

Or with unittest:

```bash
python -m unittest discover tests/
```

## Requirements

- Python 3.10 or higher

## License

MIT License — see [LICENSE](LICENSE) for details.
