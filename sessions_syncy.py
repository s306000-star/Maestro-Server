# -*- coding: utf-8 -*-
"""
This script syncs Telegram sessions stored in GitHub → into Render server.
It downloads all session files from the GitHub repository and saves them locally.
"""

import os
import requests

# Load environment variables
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO  = os.getenv("GITHUB_REPO")
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")

# GitHub API endpoint
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{SESSIONS_DIR}"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

def ensure_sessions_folder():
    """Ensure the local sessions directory exists."""
    try:
        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            print(f"📁 Created local directory: {SESSIONS_DIR}")
        else:
            print(f"📁 Using existing local directory: {SESSIONS_DIR}")
    except Exception as e:
        print("❌ Failed to create local folder:", e)


def download_sessions_from_github():
    """Download all session files from GitHub repository."""
    print("🔄 Fetching sessions list from GitHub...")

    try:
        response = requests.get(API_URL, headers=HEADERS)

        if response.status_code != 200:
            print("❌ Failed to fetch session list:", response.text)
            return

        files = response.json()
        ensure_sessions_folder()

        for file in files:

            # Only download .session or .json files
            if not (file["name"].endswith(".session") or file["name"].endswith(".json")):
                continue

            print(f"⬇️ Downloading {file['name']}...")

            download_response = requests.get(file["download_url"], headers=HEADERS)

            if download_response.status_code == 200:
                local_path = os.path.join(SESSIONS_DIR, file["name"])
                with open(local_path, "wb") as f:
                    f.write(download_response.content)

                print(f"✔ Saved → {local_path}")

            else:
                print(f"⚠️ Failed downloading → {file['name']}")

        print("🎉 All sessions downloaded successfully.")

    except Exception as e:
        print("❌ Error while syncing:", e)


if __name__ == "__main__":
    download_sessions_from_github()
