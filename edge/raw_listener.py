#!/usr/bin/env python3
"""
Raw Camera Event Listener (Throwaway Bench Capture Tool).

Run this on your laptop or gate box on port 5000 during bench setup.
When Hikvision Camera A pushes an event:
  1. Captures the exact HTTP request (multipart/XML/JSON/images).
  2. Dumps everything into 'edge/raw_captures/' for inspection.
  3. Prints detected field names so you can confirm camera firmware schema.

Usage:
  python edge/raw_listener.py --port 5000
"""

import argparse
import datetime
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Raw Camera Event Listener")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "raw_captures")
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
async def catch_all(request: Request, path: str):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    capture_dir = os.path.join(OUTPUT_DIR, f"event_{timestamp}")
    os.makedirs(capture_dir, exist_ok=True)

    print("\n" + "=" * 65)
    print(f"📸 RAW CAMERA PACKET RECEIVED: {request.method} /{path}")
    print(f"   Time: {datetime.datetime.now().isoformat()}")
    print(f"   Client IP: {request.client.host if request.client else 'unknown'}")
    print(f"   Content-Type: {request.headers.get('content-type', 'none')}")

    # 1. Save HTTP Headers
    headers_dict = dict(request.headers)
    with open(os.path.join(capture_dir, "headers.json"), "w") as f:
        json.dump(headers_dict, f, indent=2)

    # 2. Check for Multipart Form or Raw Body
    content_type = request.headers.get("content-type", "")
    summary_fields = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        print(f"   Form Fields detected: {len(form)} item(s)")

        for key, value in form.items():
            if hasattr(value, "filename") and value.filename:
                # File upload (JPEG image, XML file, etc.)
                content = await value.read()
                filename = f"{key}_{value.filename}".replace("/", "_")
                file_path = os.path.join(capture_dir, filename)
                with open(file_path, "wb") as f:
                    f.write(content)
                summary_fields.append(f"📁 File '{key}': {value.filename} ({len(content)} bytes) -> saved to {filename}")
            else:
                # Text / JSON / XML string field
                text_val = str(value)
                summary_fields.append(f"📝 Field '{key}': {text_val[:120]}...")
                text_file = os.path.join(capture_dir, f"{key}.txt")
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(text_val)

    else:
        # Raw body (JSON or XML)
        raw_body = await request.body()
        raw_path = os.path.join(capture_dir, "raw_body.bin")
        with open(raw_path, "wb") as f:
            f.write(raw_body)

        try:
            parsed_json = json.loads(raw_body.decode("utf-8"))
            with open(os.path.join(capture_dir, "body.json"), "w") as f:
                json.dump(parsed_json, f, indent=2)
            summary_fields.append(f"📝 JSON Payload: {list(parsed_json.keys())}")
        except Exception:
            try:
                body_str = raw_body.decode("utf-8", errors="replace")
                with open(os.path.join(capture_dir, "body.txt"), "w") as f:
                    f.write(body_str)
                summary_fields.append(f"📝 Text Body ({len(raw_body)} bytes): {body_str[:150]}...")
            except Exception:
                summary_fields.append(f"📦 Binary Body ({len(raw_body)} bytes)")

    for line in summary_fields:
        print(f"   - {line}")

    print(f"💾 Full capture saved to directory:\n   {capture_dir}")
    print("=" * 65)

    return JSONResponse(content={"status": "OK", "captured_at": timestamp}, status_code=200)


def main():
    parser = argparse.ArgumentParser(description="Raw Camera Push Capture Listener")
    parser.add_argument("--port", type=int, default=5000, help="Listen port (default: 5000)")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    args = parser.parse_args()

    print("\n🌲 ===================================================")
    print("🌲 HIKVISION / ANPR RAW EVENT CAPTURE BENCH LISTENER")
    print("🌲 ===================================================")
    print(f"📡 Listening on: http://{args.host}:{args.port}")
    print("👉 Configure Camera A HTTP Push to:")
    print(f"   Host: <Your_Laptop_or_GateBox_IP> | Port: {args.port} | Path: /anpr/event")
    print(f"📁 Captures will be written to: {OUTPUT_DIR}")
    print("=" * 55 + "\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
