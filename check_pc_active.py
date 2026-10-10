"""
Check if the local PC has been active recently.
Outputs `should_run=true` or `should_run=false` to GITHUB_OUTPUT.
"""
import os
import time
import json

def main():
    should_run = True
    kb_path = "data/knowledge_base.json"
    
    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                kb = json.load(f)
            discoveries = kb.get("discoveries", [])
            if discoveries:
                last_item = discoveries[-1]
                last_time_str = last_item.get("discovered_at", "")
                if last_time_str:
                    last_ts = time.mktime(time.strptime(last_time_str, "%Y-%m-%d %H:%M:%S"))
                    diff_minutes = (time.time() - last_ts) / 60.0
                    if diff_minutes < 60:
                        should_run = False
                        print(f"🟢 PC AKTIF: Son kesif {diff_minutes:.1f} dakika once yapildi.")
                        print("💡 GitHub dakikalarinizi harcamamak icin bulut gorevi atlaniyor.")
                    else:
                        print(f"🌙 PC KAPALI: Son yerel kesif {diff_minutes:.1f} dakika onceydi. Nobeti bulut devraliyor.")
        except Exception as e:
            print(f"Uyari: {e}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"should_run={'true' if should_run else 'false'}\n")
    else:
        print(f"should_run={'true' if should_run else 'false'}")

if __name__ == "__main__":
    main()
