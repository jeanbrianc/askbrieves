"""Plain command-line interface; token comes from a hidden prompt or environment."""

import argparse
import getpass
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--url", default="https://askbrieves.brianjeanbuilds.com")
    args = parser.parse_args()
    if not args.history and not args.question:
        parser.error("provide a question or --history")
    parsed_url = urllib.parse.urlsplit(args.url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        parser.error("--url must be an HTTPS service URL without credentials")
    token = os.getenv("ASKBRIEVES_TOKEN") or getpass.getpass("AskBrieves bearer token: ")
    path = "/history" if args.history else "/questions"
    data = None if args.history else json.dumps({"question": args.question}).encode()
    req = urllib.request.Request(args.url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=35) as result:
            body = json.load(result)
        print(json.dumps(body, indent=2) if args.history else body["answer"])
        return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read(4096).decode()}")
        return 1
    except (OSError, ValueError):
        print("Unable to contact AskBrieves safely.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
