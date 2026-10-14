import json
import os

STORE_FILE = "triage_store.json"

def _load():
    if not os.path.exists(STORE_FILE):
        return {}
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def save_triage(triage_record):
    store = _load()
    alert_id = str(triage_record["alert_id"])
    store[alert_id] = triage_record
    _save(store)
    return triage_record

def get_triage(alert_id):
    return _load().get(str(alert_id))

def list_triage():
    return list(_load().values())

def record_feedback(alert_id, feedback):
    store = _load()
    alert_key = str(alert_id)
    if alert_key not in store:
        return False

    record = store[alert_key]
    record["feedback"] = feedback
    record["status"] = "validated"

    correct_commit = feedback.get("correct_commit_id")
    if correct_commit and "candidates" in record:
        for candidate in record["candidates"]:
            cid = candidate.get("commit_id")
            if cid == correct_commit:
                candidate["feedback_score"] = 1.0
                candidate["feedback_status"] = "confirmed"
            else:
                candidate["feedback_score"] = max(0.05, round(float(candidate.get("feedback_score", 0.50)) - 0.25, 2))
                candidate["feedback_status"] = "rejected"

            sem = float(candidate.get("semantic_score", 0.50))
            grp = float(candidate.get("graph_score", 0.50))
            fb = float(candidate.get("feedback_score", 0.50))
            candidate["final_score"] = round((sem * 0.60) + (grp * 0.25) + (fb * 0.15), 2)

        record["candidates"].sort(key=lambda x: x.get("final_score", 0), reverse=True)
        for idx, cand in enumerate(record["candidates"], start=1):
            cand["rank"] = idx

    store[alert_key] = record
    _save(store)
    return True

def get_commit_feedback_score(commit_id: str) -> float:
    """
    Calculates a commit's historical feedback score (0.05 to 1.0)
    across all validated incidents in triage_store.json.
    """
    store = _load()
    score = 0.50  
    for record in store.values():
        feedback = record.get("feedback")
        if not feedback:
            continue
        correct_id = feedback.get("correct_commit_id")
        if not correct_id:
            continue

        candidate_ids = [c.get("commit_id") for c in record.get("candidates", [])]
        if commit_id == correct_id:
            score += 0.25
        elif commit_id in candidate_ids:
            score -= 0.15

    return round(max(0.05, min(1.0, score)), 4)

def reset_triage_store():
    if os.path.exists(STORE_FILE):
        os.remove(STORE_FILE)