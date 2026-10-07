"""Check live parser via demo-sandbox API, no secret retrieval or server changes."""
import json
from pathlib import Path
import httpx

OUT = Path(__file__).resolve().parents[2] / "docs/realdata"


def main():
    with httpx.Client(base_url="https://fsp.neuropeople.pro", timeout=90) as client:
        login = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
        if login.status_code != 200:
            result = {"status": "blocked", "stage": "sandbox_login", "http_status": login.status_code}
        else:
            data = login.json()
            response = client.post("/api/employer/needs/parse",
                                   json={"text": "Backend middle: Python, PostgreSQL, Docker. Удалённо."},
                                   headers={"Authorization": "Bearer " + data["access_token"]})
            result = {"http_status": response.status_code, "scenario": data.get("scenario"),
                      "parser": response.json()}
        (OUT / "stand_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
