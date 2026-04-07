
"""
This script generates a JSON file mapping issues to pull requests.

Usage:
    python create_issue_pr_map.py <issue_dir>

Arguments:
    issue_dir: The directory containing the issue JSON files.
"""
import json
import os
import re
import argparse

def create_issue_pr_map(issue_dir):
    """
    Scans all issue_*.json files in the specified directory,
    extracts repository, issue number, and pull request number,
    and generates a JSON file with this mapping.
    """
    output_file = os.path.join(issue_dir, 'issue_pr_map.json')
    issue_pr_map = []

    if not os.path.exists(issue_dir):
        print(f"Directory not found: {issue_dir}")
        return

    for filename in os.listdir(issue_dir):
        if filename.startswith('issue_') and filename.endswith('.json'):
            filepath = os.path.join(issue_dir, filename)
            with open(filepath, 'r') as f:
                try:
                    data = json.load(f)
                    issue_number = data.get('number')
                    repo_url = data.get('url')
                    
                    repo_match = re.search(r'github.com/([^/]+/[^/]+)', repo_url)
                    if not repo_match:
                        continue

                    repo = repo_match.group(1)

                    if 'linked_prs' in data and data['linked_prs']:
                        for pr in data['linked_prs']:
                            pr_number = pr.get('number')
                            if issue_number and repo and pr_number:
                                issue_pr_map.append({
                                    "repo": repo,
                                    "issue_number": issue_number,
                                    "pr_number": pr_number
                                })
                except json.JSONDecodeError:
                    print(f"Error decoding JSON from {filename}")
                except Exception as e:
                    print(f"An error occurred while processing {filename}: {e}")

    with open(output_file, 'w') as f:
        json.dump(issue_pr_map, f, indent=2)

    print(f"Successfully created {output_file}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create a map of issues to pull requests from JSON files.")
    parser.add_argument('issue_dir', type=str, help='The directory containing the issue JSON files.')
    args = parser.parse_args()
    create_issue_pr_map(args.issue_dir)
