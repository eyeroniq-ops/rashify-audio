import os
import time
import json
import threading
import urllib.request
import urllib.error
import ssl
from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

SLSKD_URL = os.environ.get("SLSKD_URL", "http://localhost:5030")
API_KEY = os.environ.get("SLSKD_API_KEY", "rashify-api-key-secret")
DOWNLOAD_DIR = "/app/downloads"

ssl_ctx = ssl.create_default_context()

# Track active downloads
active_downloads = {}
download_lock = threading.Lock()


def slskd_available():
    """Check if slskd is running (just check if port responds)."""
    try:
        url = f"{SLSKD_URL}/api/v0/application"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3, context=ssl_ctx) as resp:
            return resp.status in [200, 401]  # 401 = running but needs auth
    except Exception:
        return False


def slskd_request(endpoint, method="GET", body=None, timeout=15):
    """Make a request to the slskd API."""
    url = f"{SLSKD_URL}/api/v0/{endpoint}"
    # Auth disabled in config — no API key needed for internal calls
    headers = {"Content-Type": "application/json"}

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:300]
        print(f"[slskd] HTTP {e.code}: {err_body}")
        raise Exception(f"slskd error {e.code}: {err_body}")
    except Exception as e:
        print(f"[slskd] Error: {e}")
        raise


def search_soulseek(query, page=1):
    """Search Soulseek using slskd."""
    try:
        import uuid
        search_id = str(uuid.uuid4())
        body = {
            "id": search_id,
            "query": query,
            "searchText": query,
        }
        print(f"[search] Creating search {search_id} for '{query}'")
        result = slskd_request("searches", method="POST", body=body, timeout=5)
        print(f"[search] POST response: {json.dumps(result)[:300]}")

        # Wait for results
        time.sleep(3)

        # Get results
        results = slskd_request(f"searches/{search_id}", timeout=5)
        # slskd 0.25.1 uses PascalCase: "Responses" not "responses"
        responses = results.get("responses", results.get("Responses", [])) if results else []
        print(f"[search] Found {len(responses)} responses with {sum(len(r.get('files', r.get('Files', []))) for r in responses)} files")

        tracks = []
        for resp in responses:
            # Handle both camelCase and PascalCase
            username = resp.get("username", resp.get("Username", "?"))
            files = resp.get("files", resp.get("Files", []))
            for f in files:
                filename = f.get("filename", f.get("Filename", "Unknown"))
                ext = filename.lower().split(".")[-1] if "." in filename else ""
                if ext not in ["mp3", "flac", "m4a", "ogg", "opus", "wav", "aac", "wma"]:
                    continue

                name = os.path.splitext(filename)[0]
                artist = "Unknown"
                title = name
                if " - " in name:
                    parts = name.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()

                size = f.get("size", f.get("Size", 0))
                bitrate = f.get("bitRate", f.get("BitRate", f.get("bitrate", 0)))

                tracks.append({
                    "id": f"{username}//{filename}",
                    "title": title,
                    "artist": artist,
                    "duration": f.get("length", f.get("Length", 180)),
                    "cover": "",
                    "source": "soulseek",
                    "size": size,
                    "bitrate": bitrate,
                    "ext": ext.upper(),
                    "username": username,
                })

        tracks.sort(key=lambda t: t.get("bitrate", 0), reverse=True)
        offset = (page - 1) * 30
        print(f"[search] Returning {len(tracks[offset:offset+30])} tracks", flush=True)
        return tracks[offset:offset + 30]

    except Exception as e:
        print(f"[search] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []


def download_from_soulseek(filename, username, size):
    """Download a file from Soulseek via slskd."""
    download_id = f"{username}//{filename}"

    with download_lock:
        if download_id in active_downloads:
            return active_downloads[download_id]

    try:
        # Queue download via slskd
        body = {
            "filename": filename,
            "username": username,
            "size": size or 0,
        }
        slskd_request(f"transfers/downloads/{username}", method="POST", body=body, timeout=5)

        # Wait for download to complete (poll)
        max_wait = 120  # 2 minutes max
        file_path = os.path.join(DOWNLOAD_DIR, filename)

        for _ in range(max_wait):
            time.sleep(1)
            if os.path.exists(file_path):
                # Give it a moment to finish writing
                time.sleep(0.5)
                actual_size = os.path.getsize(file_path)
                if actual_size > 0:
                    print(f"[soulseek] Downloaded: {filename} ({actual_size / 1024 / 1024:.1f} MB)")
                    with download_lock:
                        active_downloads[download_id] = file_path
                    return file_path

        # Check incomplete directory too
        incomplete_dir = "/app/incomplete"
        for f in os.listdir(incomplete_dir) if os.path.exists(incomplete_dir) else []:
            if filename in f:
                print(f"[soulseek] Found incomplete: {f}")

        raise Exception(f"Download timeout: {filename}")

    except Exception as e:
        print(f"[soulseek] Download error: {e}")
        with download_lock:
            active_downloads.pop(download_id, None)
        raise


@app.route("/debug_search")
def debug_search():
    """Debug endpoint: return raw slskd API response for a search."""
    query = request.args.get("q", "daft punk")
    try:
        import uuid
        search_id = str(uuid.uuid4())
        body = {"id": search_id, "query": query, "searchText": query}

        # Create search
        create_resp = slskd_request("searches", method="POST", body=body, timeout=5)

        # Wait
        time.sleep(4)

        # Get results
        results = slskd_request(f"searches/{search_id}", timeout=5)

        return jsonify({
            "search_id": search_id,
            "create_response": create_resp,
            "results": results,
            "num_responses": len(results.get("responses", [])) if results else 0,
        })
    except Exception as e:
        return jsonify(error=str(e), traceback=str(__import__('traceback').format_exc()))


@app.route("/logs")
def logs():
    """Read slskd logs for debugging."""
    logs = {}
    for name in ["/tmp/slskd-stdout.log", "/tmp/slskd-stderr.log"]:
        try:
            with open(name, "r") as f:
                logs[name] = f.read()[-5000:]
        except Exception:
            logs[name] = "(not found)"
    return jsonify(logs)


@app.route("/")
def health():
    slskd_ok = slskd_available()
    info = {"status": "ok" if slskd_ok else "starting", "slskd": slskd_ok}
    if slskd_ok:
        try:
            app_info = slskd_request("application", timeout=3)
            info["soulseek_connected"] = app_info.get("state", {}).get("isConnected", False)
        except Exception as e:
            info["error"] = str(e)[:200]
    return jsonify(info)


@app.route("/search")
def search():
    query = request.args.get("q", "")
    page = int(request.args.get("page", 1))
    source = request.args.get("source", "soulseek")

    if not query.strip():
        return jsonify(tracks=[])

    print(f"[search] q={query} page={page} source={source}")

    tracks = []
    if source == "soulseek":
        tracks = search_soulseek(query, page)

    return jsonify(tracks=tracks)


@app.route("/audio")
def audio():
    """Stream audio file. Downloads from Soulseek if not cached."""
    track_id = request.args.get("id", "")
    filename = request.args.get("filename", "")
    username = request.args.get("username", "")
    size = int(request.args.get("size", 0))

    if not filename or not username:
        return jsonify(error="Need filename and username params"), 400

    print(f"[audio] {username}//{filename}")

    try:
        file_path = download_from_soulseek(filename, username, size)
        ext = file_path.split(".")[-1].lower()
        mime_map = {
            "mp3": "audio/mpeg",
            "flac": "audio/flac",
            "m4a": "audio/mp4",
            "ogg": "audio/ogg",
            "opus": "audio/opus",
            "wav": "audio/wav",
            "aac": "audio/aac",
            "wma": "audio/x-ms-wma",
        }
        mime = mime_map.get(ext, "audio/mpeg")
        print(f"[audio] Serving: {file_path} as {mime}")

        return send_file(file_path, mimetype=mime, as_attachment=False)

    except Exception as e:
        print(f"[audio] Error: {e}")
        return jsonify(error=str(e)[:300]), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Rashify Soulseek API → http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
