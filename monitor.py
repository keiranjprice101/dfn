#!/usr/bin/env python3
"""
Long‑lived directory watcher script that forwards notifications to a Discord
webhook.  The directory to monitor and the webhook URL are provided via
environment variables.  When a new file is created in the monitored
directory the script sends a message to the webhook with the file name.

Discord’s documentation explains that the request body must include a
`content`, `embeds`, `poll` or attachment field, otherwise the request will
fail【615489115346845†L55-L60】.  A simple JSON object with a `content`
attribute is sufficient for basic messages【728709583288637†L42-L47】.  This script
uses the `content` field to send plain text notifications.  It also
implements basic rate‑limit handling by respecting the `Retry‑After` header
returned from Discord on HTTP 429 responses【728709583288637†L74-L90】.

Environment variables:

* ``DISCORD_WEBHOOK_URL`` – The full webhook URL generated in your
  Discord channel settings.  Treat this value as a secret【728709583288637†L66-L71】.
* ``WATCH_DIRECTORY`` – Absolute path of the directory to monitor.  If
  unset the script defaults to ``/data``.

Dependencies: this script uses the `watchdog` package for efficient
filesystem watching and `requests` for HTTP communication.  They can be
installed with ``pip install watchdog requests``.  When packaging this
application in Docker the corresponding `Dockerfile` installs these
dependencies.
"""

import os
import time
import logging
from queue import Queue
from threading import Thread
from typing import Optional

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

WEBHOOK_URL: Optional[str] = os.getenv("DISCORD_WEBHOOK_URL")
MONITOR_DIR: str = os.getenv("WATCH_DIRECTORY", "/data")


def validate_config() -> bool:
    """Validate environment variables.  Returns True if configuration is
    complete, otherwise logs an error and returns False."""
    if not WEBHOOK_URL:
        logging.error(
            "The DISCORD_WEBHOOK_URL environment variable is not set. "
            "Create a webhook in your Discord server and set this variable to the full URL.")
        return False
    if not os.path.isdir(MONITOR_DIR):
        logging.error(
            "The directory to watch does not exist: %s",
            MONITOR_DIR,
        )
        return False
    return True


def send_discord_message(file_path: str) -> None:
    """Post a message to the Discord webhook announcing a new file.

    If Discord responds with a rate‑limit status (HTTP 429) then the
    function waits for the number of seconds indicated by the
    ``Retry‑After`` header before retrying【728709583288637†L74-L90】.

    Args:
        file_path: absolute path of the file that triggered the event.
    """
    file_name = os.path.basename(file_path)
    url = ("http://192.168.5.22:8080/files/hdd2/Octocrate" + file_path.replace("/data", "")).replace(" ", "%20")
    # Compose the message.  Keep it simple: the `content` field is
    # sufficient for a basic message【728709583288637†L42-L47】.
    payload = {
        "content": f"🆕 file detected: <{url}> in monitored directory."
    }
    while True:
        try:
            response = requests.post(WEBHOOK_URL, json=payload)
        except Exception as exc:
            logging.error("Error sending webhook for %s: %s", file_name, exc)
            # Wait a bit before retrying on network errors
            time.sleep(5)
            continue
        # 204 No Content or 200 OK indicates success
        if response.status_code in (200, 204):
            logging.info("Notification sent for %s", file_name)
            break
        if response.status_code == 429:
            # Rate limited; wait and retry【728709583288637†L74-L90】
            retry_after = response.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after)
            except (TypeError, ValueError):
                wait_seconds = 2.0  # fallback if header missing or invalid
            logging.warning(
                "Rate limited by Discord. Waiting %.2f seconds before retrying...",
                wait_seconds,
            )
            time.sleep(wait_seconds)
            continue
        else:
            logging.error(
                "Unexpected response %s when sending webhook: %s", response.status_code, response.text
            )
            break


class NewFileHandler(FileSystemEventHandler):
    """Handler that enqueues new file events for processing."""

    def __init__(self, queue: Queue) -> None:
        self.queue = queue

    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self.queue.put(event.src_path)


def worker(queue: Queue) -> None:
    """Worker thread that sends Discord notifications for queued file paths."""
    while True:
        path = queue.get()
        if path is None:
            break
        send_discord_message(path)
        queue.task_done()


def main() -> None:
    if not validate_config():
        return
    event_queue: Queue = Queue()
    handler = NewFileHandler(event_queue)
    observer = Observer()
    observer.schedule(handler, MONITOR_DIR, recursive=False)
    observer.start()
    logging.info("Watching directory: %s", MONITOR_DIR)
    # Launch a worker thread to process queued events
    worker_thread = Thread(target=worker, args=(event_queue,), daemon=True)
    worker_thread.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutdown requested by user. Stopping observer...")
        observer.stop()
    observer.join()
    # Signal worker to exit and wait for queue completion
    event_queue.put(None)
    event_queue.join()


if __name__ == "__main__":
    main()