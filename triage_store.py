import json
import os

STORE_FILE = "triage_store.json"

def _load():
    if not os.path.exists(STORE_FILE):
        return {}
    try:
        with open(STORE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data):
    with open(STORE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def save_triage(triage_record):
    store = _load()
    store[triage_record["alert_id"]] = triage_record
    _save(store)

def get_triage(alert_id):
    return _load().get(alert_id)

def list_triage():
    return list(_load().values())

def record_feedback(alert_id, feedback):
    store = _load()
    if alert_id in store:
        store[alert_id]["feedback"] = feedback
        store[alert_id]["status"] = "validated"
        _save(store)
        return True
    return False

def reset_triage_store():
    if os.path.exists(STORE_FILE):
        os.remove(STORE_FILE)