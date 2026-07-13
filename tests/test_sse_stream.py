"""Quick test to verify SSE stream terminates properly."""
import requests
import json
import sys

BASE = "http://localhost:7000"

def test_stream():
    print("Sending chat request...")
    resp = requests.post(
        f"{BASE}/api/chat",
        json={"message": "你好", "file_refs": []},
        stream=True,
        timeout=60,
    )
    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
    print("--- Events ---")

    event_count = 0
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data: "):
            data = line[6:]
            try:
                event = json.loads(data)
                ev_type = event.get("type", "?")
                ev_content = event.get("content", "")
                # Truncate long content for readability
                display = ev_content[:80] + "..." if len(ev_content) > 80 else ev_content
                print(f"  [{ev_type}] {display}")
                event_count += 1

                if ev_type == "done":
                    print(f"\n✅ Stream completed normally. Total events: {event_count}")
            except json.JSONDecodeError:
                print(f"  [RAW] {data[:100]}")

    print(f"\n--- Stream closed by server. Total events: {event_count} ---")


if __name__ == "__main__":
    try:
        test_stream()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except requests.exceptions.ConnectionError as e:
        print(f"\n❌ Cannot connect to {BASE}. Is the server running?")
        sys.exit(1)
