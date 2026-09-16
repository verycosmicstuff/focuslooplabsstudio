# Focusloop Labs Website Deployment Runbook

This document permanently records the exact repositories, file locations, and git/API commands for deploying **`https://focuslooplabs.vercel.app/`**.

---

## 1. Connected Repositories

| Repository | Role | Purpose |
| :--- | :--- | :--- |
| **`verycosmicstuff/cec-tracker`** | Primary Vercel Repo | Deploys `https://focuslooplabs.vercel.app/` |
| **`verycosmicstuff/cec-data`** | Production Mirror Repo | Synced static backup |
| **`verycosmicstuff/focuslooplabsstudio`** | App Core & Releases | Holds code & GitHub Release downloads |

---

## 2. File Locations

### A. Homepage (`https://focuslooplabs.vercel.app/`)
- **`cec-tracker`**: `focusloop_home.html` & `www/focusloop_home.html`
- **`cec-data`**: `index.html`

### B. Studio Landing Page (`https://focuslooplabs.vercel.app/studio.html`)
- **`cec-tracker`**: `studio.html` & `www/studio.html`
- **`cec-data`**: `studio.html`

---

## 3. Fast Git Commands

```bash
# Clone both:
git clone https://github.com/verycosmicstuff/cec-tracker.git
git clone https://github.com/verycosmicstuff/cec-data.git

# In cec-tracker:
# Edit focusloop_home.html, www/focusloop_home.html, studio.html, www/studio.html
git -C cec-tracker add . ; git -C cec-tracker commit -m "feat: update release links" ; git -C cec-tracker push origin main

# In cec-data:
# Edit index.html, studio.html
git -C cec-data add . ; git -C cec-data commit -m "feat: update release links" ; git -C cec-data push origin main
```

---

## 4. Instant Update Script via GitHub API (Zero-Clone)

Run in python:
```python
import urllib.request, json, base64

# Token retrieved via: 'protocol=https\nhost=github.com\n' | git credential fill
TOKEN = "gho_..." 

def update_file(repo, file_path, content_str, commit_msg):
    url = f"https://api.github.com/repos/verycosmicstuff/{repo}/contents/{file_path}"
    headers = {
        "User-Agent": "FocusloopDeployer",
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    req = urllib.request.Request(url, headers=headers)
    res = json.loads(urllib.request.urlopen(req).read().decode())
    sha = res["sha"]
    payload = json.dumps({
        "message": commit_msg,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }).encode("utf-8")
    req_put = urllib.request.Request(url, data=payload, headers=headers, method="PUT")
    with urllib.request.urlopen(req_put) as resp:
        print(f"Updated {repo}/{file_path}: status {resp.status}")
```
