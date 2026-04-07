import json
import os
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv


agent_dir = os.path.join(os.path.dirname(__file__), '..', '..')
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)


class StatsTool:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.stats_file = "claude/stat.json"

        # Load .env
        possible_env_paths = [
            Path(__file__).parent.parent.parent / '.env',
            Path(__file__).parent.parent.parent.parent / '.env',
            Path.cwd() / '.env',
        ]

        for env_path in possible_env_paths:
            if env_path.exists():
                load_dotenv(env_path)
                if self.verbose:
                    print(f"Loaded environment from: {env_path}")
                break
        else:
            print("Warning: No .env file found")

        self.api_key = os.getenv("FORGE_API_KEY", "").strip('"').strip("'")
        self.base_url = os.getenv(
            "FORGE_BASE_URL",
            "https://api.forge.tensorblock.co/v1"
        ).strip('"').strip("'")

        model_config = os.getenv("MODEL")
        if not model_config:
            print("Error: MODEL environment variable not set")
            sys.exit(1)

        model_config = model_config.strip('"').strip("'")

        if '/' in model_config:
            self.provider, self.model = model_config.split('/', 1)
        else:
            self.provider = "OpenAI"
            self.model = model_config

        if not self.api_key:
            print("Warning: FORGE_API_KEY not set properly")

    # -------------------------
    # SAFE JSON EXTRACTION
    # -------------------------

    def _extract_list_from_response(self, json_data):
        """
        Extract a list of usage records safely from API response.
        Handles multiple possible API formats.
        """

        if isinstance(json_data, list):
            return json_data

        if isinstance(json_data, dict):
            for key in ["data", "results", "items"]:
                if key in json_data and isinstance(json_data[key], list):
                    return json_data[key]

        if self.verbose:
            print("Unexpected API response format:")
            print(json_data)

        return None

    # -------------------------
    # API CALLS
    # -------------------------

    def get_api_stats(self) -> Optional[List[Dict[str, Any]]]:
        if not self.api_key:
            print("Error: FORGE_API_KEY not available")
            return None

        try:
            base_url = self.base_url.rstrip('/')
            stats_url = f"{base_url}/stats/?provider={self.provider}&model={self.model}"

            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = requests.get(stats_url, headers=headers, timeout=30)

            if response.status_code != 200:
                print(f"Error getting API stats: HTTP {response.status_code}")
                print(response.text)
                return None

            json_data = response.json()

            if self.verbose:
                print("Raw API response:", json_data)

            return self._extract_list_from_response(json_data)

        except Exception as e:
            print(f"Error getting API stats: {str(e)}")
            return None

    def get_all_paginated_stats(self, session_start: str, session_end: str):
        if not self.api_key:
            print("Error: FORGE_API_KEY not available")
            return None

        try:
            base_url = self.base_url.rstrip('/')
            headers = {"Authorization": f"Bearer {self.api_key}"}

            params = {
                "provider_name": self.provider,
                "model_name": self.model,
                "started_at": session_start,
                "ended_at": session_end,
                "limit": 2000
            }

            response = requests.get(
                f"{base_url}/statistic/usage/realtime",
                headers=headers,
                params=params,
                timeout=30
            )

            if response.status_code != 200:
                print(f"Error getting data: HTTP {response.status_code}")
                print(response.text)
                return None

            json_data = response.json()

            if self.verbose:
                print("Raw paginated response:", json_data)

            return self._extract_list_from_response(json_data)

        except Exception as e:
            print(f"Error getting paginated stats: {str(e)}")
            return None

    # -------------------------
    # FILE HANDLING
    # -------------------------

    def load_existing_stats(self):
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

        return {
            "session_start": None,
            "session_end": None,
            "start_stats": None,
            "end_stats": None,
            "usage_delta": None,
            "execution_info": {},
            "api_info": {
                "provider_name": None,
                "model": None
            }
        }

    def save_stats(self, stats_data):
        os.makedirs(os.path.dirname(self.stats_file), exist_ok=True)
        with open(self.stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)

    # -------------------------
    # SESSION START
    # -------------------------

    def record_session_start(self):
        stats_data = self.load_existing_stats()
        current_time = datetime.now(timezone.utc).isoformat()

        start_stats = {
            "provider_name": self.provider,
            "model": self.model,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "requests_count": 0,
            "cost": 0.0
        }

        stats_data["session_start"] = current_time
        stats_data["start_stats"] = [start_stats]
        stats_data["api_info"]["provider_name"] = self.provider
        stats_data["api_info"]["model"] = self.model

        self.save_stats(stats_data)
        print("Session start recorded.")

    # -------------------------
    # SESSION END (FIXED)
    # -------------------------

    def record_session_end(self):
        stats_data = self.load_existing_stats()
        current_time = datetime.now(timezone.utc).isoformat()

        session_start = stats_data.get("session_start") or current_time

        all_session_data = self.get_all_paginated_stats(
            session_start,
            current_time
        )

        stats_data["session_end"] = current_time

        if not all_session_data:
            print("No usage data found.")
            stats_data["end_stats"] = []
            stats_data["usage_delta"] = None
            self.save_stats(stats_data)
            return

        # Safe aggregation
        valid_items = [
            item for item in all_session_data
            if isinstance(item, dict)
        ]

        total_input_tokens = sum(item.get("input_tokens", 0) for item in valid_items)
        total_output_tokens = sum(item.get("output_tokens", 0) for item in valid_items)
        total_tokens = sum(
            item.get("total_tokens", item.get("tokens", 0))
            for item in valid_items
        )
        total_cost = sum(float(item.get("cost", 0)) for item in valid_items)
        requests_count = len(valid_items)

        session_stats = {
            "provider_name": self.provider,
            "model": self.model,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "requests_count": requests_count,
            "cost": total_cost
        }

        stats_data["end_stats"] = [session_stats]
        stats_data["usage_delta"] = session_stats

        self.save_stats(stats_data)

        print("Session usage summary:")
        print(f"  Requests: {requests_count}")
        print(f"  Input tokens: {total_input_tokens:,}")
        print(f"  Output tokens: {total_output_tokens:,}")
        print(f"  Total tokens: {total_tokens:,}")
        print(f"  Cost: ${total_cost:.6f}")

    # -------------------------
    # RUN
    # -------------------------

    def run(self, action: str):
        if action == "start":
            self.record_session_start()
        elif action == "end":
            self.record_session_end()
        elif action == "check":
            stats = self.get_api_stats()
            if stats:
                print("Current API stats:")
                for item in stats:
                    print(json.dumps(item, indent=2))
            else:
                print("Could not retrieve API stats")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="API Stats Tool")
    parser.add_argument("action", choices=["start", "end", "check"])
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    tool = StatsTool(verbose=args.verbose)
    tool.run(args.action)


if __name__ == "__main__":
    main()