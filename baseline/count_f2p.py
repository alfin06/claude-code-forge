#!/usr/bin/env python3
#!/usr/bin/env python3
"""
count_f2p.py

This script scans all f2p_report.json files in the run_instances/swegent_f2p/{folder}/ directories.
It counts:
  - The number of cases (f2p count) where:
      * "build_ok" is true and "test_ok" is false in the "before" section, and
      * "build_ok" is true and "test_ok" is true in the "after" section.
  - The number of cases (env count) where:
      * "build_ok" is true in both the "before" and "after" sections.

For each count, it also prints the corresponding issue_url values so you can see which issues are included in each category.

Usage:
    python count_f2p.py

Place this script in the baseline directory and run from there.
"""

import os
import json

RUN_INSTANCES_DIR = "/home/cc/repo/claude-code-forge/run_instances/swegent_f2p"

def main():
    f2p_count = 0
    env_count = 0
    env_issue_urls = []
    f2p_issue_urls = []
    for folder in os.listdir(RUN_INSTANCES_DIR):
        report_path = os.path.join(RUN_INSTANCES_DIR, folder, "f2p_report.json")
        if not os.path.isfile(report_path):
            continue
        with open(report_path, "r") as f:
            data = json.load(f)
        before = data.get("before", {})
        after = data.get("after", {})
        issue_url = data.get("issue_url", "(no issue_url)")
        # env_count: both before and after build_ok are true
        if before.get("build_ok") and after.get("build_ok"):
            env_count += 1
            env_issue_urls.append(issue_url)
            # f2p_count: before build_ok False, test_ok false; after build_ok true, test_ok true
            if before.get("test_ok") is False and after.get("test_ok") is True:
                f2p_count += 1
                f2p_issue_urls.append(issue_url)
    print(f"f2p count: {f2p_count}")
    print("f2p issue_urls:")
    for url in f2p_issue_urls:
        print(f"  {url}")
    print(f"env count: {env_count}")
    print("env issue_urls:")
    for url in env_issue_urls:
        print(f"  {url}")

if __name__ == "__main__":
    main()
