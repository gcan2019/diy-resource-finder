"""
Safe cloud sync script for GitHub Actions and local sync.
Merges local discoveries with remote origin/main discoveries without EVER creating git conflict markers.
"""
import sys
import re
import json
import subprocess
from pathlib import Path

def sanitize_json_text(text: str) -> str:
    lines = [l for l in text.splitlines() if not re.match(r'^[<>=]{7}', l)]
    return "\n".join(lines)

def load_clean_discoveries(path: Path) -> list:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        clean_raw = sanitize_json_text(raw)
        data = json.loads(clean_raw)
        return data.get("discoveries", [])
    except Exception as e:
        print(f"Warning loading {path}: {e}")
        return []

def main():
    kb_path = Path("data/knowledge_base.json")
    local_disc = load_clean_discoveries(kb_path)
    print(f"Local discoveries: {len(local_disc)}")

    # Fetch origin/main safely
    subprocess.run(["git", "fetch", "origin", "main"], check=False)
    
    # Get remote knowledge_base.json via git show
    remote_disc = []
    res = subprocess.run(["git", "show", "origin/main:data/knowledge_base.json"], capture_output=True, text=True, encoding="utf-8")
    if res.returncode == 0 and res.stdout:
        try:
            remote_data = json.loads(sanitize_json_text(res.stdout))
            remote_disc = remote_data.get("discoveries", [])
            print(f"Remote discoveries from origin/main: {len(remote_disc)}")
        except Exception as e:
            print(f"Error parsing remote KB: {e}")

    # Merge and deduplicate by page_url
    merged_map = {}
    for d in remote_disc + local_disc:
        url = d.get("page_url")
        if url:
            merged_map[url] = d
        else:
            merged_map[id(d)] = d

    all_merged = list(merged_map.values())
    print(f"Total merged & deduplicated: {len(all_merged)}")

    # Sort by discovered_at
    all_merged.sort(key=lambda x: x.get("discovered_at", ""))

    # Save to knowledge_base.json with automated backup
    clean_kb = {"discoveries": all_merged}
    kb_path.write_text(json.dumps(clean_kb, indent=2, ensure_ascii=False), encoding="utf-8")
    Path("data/knowledge_base.backup.json").write_text(json.dumps(clean_kb, indent=2, ensure_ascii=False), encoding="utf-8")

    # Update catalogs
    try:
        from autonomous_agent import update_markdown_catalog
        update_markdown_catalog(clean_kb)
    except Exception as e:
        print(f"Warning updating catalogs: {e}")

    print("Knowledge base & catalogs safely synced without conflicts.")

if __name__ == "__main__":
    main()
