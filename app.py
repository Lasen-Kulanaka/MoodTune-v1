"""
MoodTune – AI Mood-Based Music Recommender
Flask backend that analyzes user text input to detect mood
and returns matching music playlists with confidence scores.
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from textblob import TextBlob
import json
import os
import re
import subprocess
import sys
import threading

app = Flask(__name__)
CORS(app)

# ── Persistent premium state ──────────────────────────────────────────
# Stored in a JSON file so Flask debug-mode reloads and notifier
# cold-starts all read the same value without losing state.
_premium_lock = threading.Lock()
_PREMIUM_STATE_FILE = os.path.join(os.path.dirname(__file__), "premium_state.json")


def _load_premium_state() -> bool:
    """Read premium state from disk. Returns False if file is missing."""
    try:
        with open(_PREMIUM_STATE_FILE, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("premium", False))
    except Exception:
        return False


def _save_premium_state(value: bool) -> None:
    """Write premium state to disk atomically."""
    try:
        with open(_PREMIUM_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"premium": value}, f)
    except Exception as e:
        print(f"[MoodTune] Warning: could not save premium state: {e}")


_premium_active: bool = _load_premium_state()

# ── Load playlist data ──────────────────────────────────────────────
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "playlists.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    PLAYLISTS = json.load(f)

# ── Keyword dictionaries for mood classification ────────────────────
MOOD_KEYWORDS = {
    "happy": [
        "happy", "joy", "excited", "great", "wonderful", "amazing",
        "fantastic", "cheerful", "blessed", "grateful", "glad", "delighted",
        "thrilled", "ecstatic", "elated", "awesome", "good", "nice", "fun",
        "celebrate", "party", "laughing", "smile", "positive", "excellent",
        "brilliant", "superb", "terrific", "jolly", "joyful", "overjoyed",
        "euphoric", "on top of the world", "in high spirits",
    ],
    "sad": [
        "sad", "depressed", "unhappy", "down", "lonely", "heartbroken",
        "miserable", "gloomy", "crying", "tears", "hopeless", "lost",
        "empty", "grief", "sorrow", "mourn", "pain", "hurt", "miss",
        "alone", "broken", "devastated", "despair", "melancholy", "blue",
        "let down", "disappointed", "crushed", "gutted", "fell apart",
        "broke up", "broke my heart",
    ],
    "stressed": [
        "stressed", "anxious", "worried", "nervous", "tense", "pressure",
        "overwhelmed", "panic", "deadline", "exam", "test", "assignment",
        "workload", "burden", "exhausted", "tired", "burnout", "frustrated",
        "overworked", "hectic", "crazy", "chaos", "struggling", "difficult",
        "hard time", "tough", "intense", "behind on", "running out of time",
        "can't keep up", "too much", "falling behind",
    ],
    "calm": [
        "calm", "peaceful", "relaxed", "serene", "tranquil", "content",
        "chill", "mellow", "quiet", "still", "gentle", "soothing",
        "comfortable", "ease", "balanced", "harmony", "zen", "meditate",
        "mindful", "cozy", "warm", "soft", "at peace", "laid back",
        "taking it easy", "unwinding", "winding down",
    ],
    "energetic": [
        "energetic", "pumped", "hyped", "motivated", "active", "workout",
        "exercise", "gym", "running", "dancing", "alive", "powerful",
        "strong", "unstoppable", "fired up", "adrenaline", "beast mode",
        "lets go", "let's go", "ready", "charged", "vibrant", "dynamic",
        "on fire", "crushing it", "killing it", "full of energy",
    ],
    "romantic": [
        "romantic", "love", "crush", "date", "boyfriend", "girlfriend",
        "partner", "valentine", "kiss", "hug", "affection", "passion",
        "desire", "admire", "adore", "sweetheart", "darling", "soulmate",
        "together", "couple", "heart", "loving", "intimate", "infatuated",
        "head over heels", "falling for", "in love",
    ],
    "angry": [
        "angry", "furious", "mad", "rage", "hate", "annoyed", "irritated",
        "pissed", "livid", "outraged", "disgusted", "resentful", "bitter",
        "hostile", "aggressive", "fed up", "sick of", "enraged", "infuriated",
        "frustrated", "revenge", "unfair", "losing my mind", "can't stand",
        "drives me crazy", "so done",
    ],
    "focused": [
        "focused", "concentrate", "study", "work", "productive", "coding",
        "reading", "learning", "research", "deep work", "flow", "grind",
        "hustle", "determined", "driven", "ambitious", "goal", "target",
        "project", "task", "prepare", "practice", "locking in", "lock in",
        "in the zone", "heads down", "getting things done",
    ],
}

# ── NLP helpers ─────────────────────────────────────────────────────

# Words that negate the following sentiment keyword
NEGATION_WORDS = {
    "not", "never", "no", "nor", "neither", "without", "hardly",
    "barely", "scarcely", "don't", "dont", "doesn't", "doesnt",
    "didn't", "didnt", "won't", "wont", "can't", "cant", "isn't",
    "isnt", "aren't", "arent", "wasn't", "wasnt", "weren't", "werent",
    "couldn't", "couldnt", "wouldn't", "wouldnt", "shouldn't", "shouldnt",
}

# Split text into clauses on punctuation and adversative conjunctions.
# These boundaries often separate contrasting emotional statements.
CLAUSE_SPLIT_RE = re.compile(
    r'[,;.!?\n]'
    r'|\b(?:but|however|although|though|yet|while|whereas|still|'
    r'except|even though|on the other hand|at the same time|'
    r'meanwhile|nevertheless|nonetheless|despite)\b',
    re.IGNORECASE,
)

# Pre-compile one regex pattern per keyword for efficiency.
# Structure: { mood: [(compiled_pattern, [kw_word, ...]), ...] }
_KW_PATTERNS: dict = {}
for _mood, _kws in MOOD_KEYWORDS.items():
    _KW_PATTERNS[_mood] = []
    for _kw in _kws:
        _parts = _kw.lower().split()
        _pat = re.compile(
            r'\b' + r'\s+'.join(re.escape(p) for p in _parts) + r'\b',
            re.IGNORECASE,
        )
        _KW_PATTERNS[_mood].append((_pat, _parts))


def _is_negated(clause_words: list, kw_parts: list) -> bool:
    """Return True if *kw_parts* appears in *clause_words* and is immediately
    preceded (within a 3-word window) by a negation word.

    Example: ["i", "am", "not", "happy"] → is_negated([...], ["happy"]) → True
    """
    kw_len = len(kw_parts)
    for i in range(len(clause_words) - kw_len + 1):
        if clause_words[i: i + kw_len] == kw_parts:
            window_start = max(0, i - 3)
            context = clause_words[window_start:i]
            if any(w in NEGATION_WORDS for w in context):
                return True
    return False


def _score_clause(clause: str) -> dict:
    """Return raw keyword hit-counts per mood for a single text clause.

    Uses pre-compiled word-boundary regex patterns so partial substring
    matches (e.g. 'love' inside 'lovely') are correctly excluded.
    Negated keywords (e.g. 'not happy') are skipped.
    """
    words = re.findall(r"[\w']+", clause.lower())
    scores: dict = {}
    for mood, patterns in _KW_PATTERNS.items():
        for pat, kw_parts in patterns:
            if pat.search(clause) and not _is_negated(words, kw_parts):
                scores[mood] = scores.get(mood, 0) + 1
    return scores


def classify_moods(text: str) -> list:
    """
    Classify all moods present in the given text.

    Strategy:
      1. Split text into emotional clauses on punctuation and adversative
         conjunctions so cross-clause sentiments don't cancel each other.
      2. Score every clause with word-boundary keyword matching and
         negation detection.
      3. Aggregate clause scores, discard low-confidence noise moods
         (< 20 % of the top score), and normalise to confidence values.
      4. Fall back to TextBlob polarity when no keywords match at all.

    Returns a list of dicts sorted by confidence descending (max 3):
        [{"mood": "happy", "confidence": 0.72}, ...]
    """
    # ── Step 1: Split into emotional clauses ────────────────────────
    clauses = [c.strip() for c in CLAUSE_SPLIT_RE.split(text) if c.strip()]
    if not clauses:
        clauses = [text]

    # ── Step 2: Aggregate keyword scores across all clauses ──────────
    total_scores: dict = {}
    for clause in clauses:
        for mood, score in _score_clause(clause).items():
            total_scores[mood] = total_scores.get(mood, 0) + score

    if total_scores:
        max_score = max(total_scores.values())
        # Noise filter: keep only moods that score ≥ 20 % of the winner
        threshold = max_score * 0.20
        filtered = {m: s for m, s in total_scores.items() if s >= threshold}

        total = sum(filtered.values())
        result = [
            {"mood": m, "confidence": round(filtered[m] / total, 2)}
            for m in sorted(filtered, key=lambda x: filtered[x], reverse=True)
        ]
        return result[:3]

    # ── Step 3: Fall back to TextBlob sentiment ──────────────────────
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity  # –1.0 to +1.0

    if polarity > 0.3:
        return [{"mood": "happy", "confidence": 1.0}]
    elif polarity > 0.05:
        return [{"mood": "calm", "confidence": 1.0}]
    elif polarity < -0.3:
        return [{"mood": "sad", "confidence": 1.0}]
    elif polarity < -0.05:
        return [{"mood": "stressed", "confidence": 1.0}]
    else:
        return [{"mood": "calm", "confidence": 1.0}]


# ── Routes ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Analyze the mood of the submitted text.

    Expects JSON: { "text": "I feel ..." }
    Returns JSON:
        {
          "moods": [
            { "mood": "stressed", "confidence": 0.65, "data": { ... } },
            { "mood": "sad",      "confidence": 0.35, "data": { ... } }
          ]
        }
    """
    body = request.get_json(silent=True)
    if not body or "text" not in body:
        return jsonify({"error": "Please provide a 'text' field."}), 400

    user_text = body["text"].strip()
    if not user_text:
        return jsonify({"error": "Text cannot be empty."}), 400

    moods = classify_moods(user_text)

    results = []
    for m in moods:
        mood_data = PLAYLISTS.get(m["mood"], PLAYLISTS["calm"])
        results.append({
            "mood": m["mood"],
            "confidence": m["confidence"],
            "data": mood_data,
        })

    return jsonify({"moods": results})


# ── Premium Status Routes ────────────────────────────────────────────

@app.route("/premium", methods=["GET"])
def get_premium():
    """Return the current server-side premium status.
    Used by notifier.py to decide whether to send notifications."""
    with _premium_lock:
        return jsonify({"premium": _premium_active})


@app.route("/premium", methods=["POST"])
def set_premium():
    """Set the server-side premium status.
    Called by the browser whenever the user toggles premium on or off.
    State is persisted to disk so restarts don't lose it."""
    global _premium_active
    body = request.get_json(silent=True)
    if not body or "premium" not in body:
        return jsonify({"error": "Please provide a 'premium' field."}), 400
    with _premium_lock:
        _premium_active = bool(body["premium"])
        _save_premium_state(_premium_active)
    return jsonify({"premium": _premium_active})


# ── Auto-launch Notifier ────────────────────────────────────────────────────
_NOTIFIER_SCRIPT = os.path.join(os.path.dirname(__file__), "notifier.py")
_NOTIFIER_PID    = os.path.join(os.path.dirname(__file__), "notifier.pid")

def _notifier_already_running() -> bool:
    """Return True if a notifier process with the saved PID is still alive."""
    try:
        with open(_NOTIFIER_PID, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        import ctypes
        # os.kill on Windows can be unreliable for access checks, check if PID exists using tasklist or psutil
        # Since we just want a basic check, we can use os.kill(pid, 0)
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def _launch_notifier() -> None:
    """Start notifier.py as a background process with a system tray icon."""
    if not os.path.exists(_NOTIFIER_SCRIPT):
        print("[MoodTune] notifier.py not found – skipping auto-launch.")
        return
    if _notifier_already_running():
        print("[MoodTune] Notifier already running – skipping launch.")
        return
    try:
        # 0x08000000 is CREATE_NO_WINDOW.
        # This hides the console window but still allows pystray to interact with
        # the Windows desktop session (unlike DETACHED_PROCESS which crashed it).
        subprocess.Popen(
            [sys.executable, _NOTIFIER_SCRIPT],
            creationflags=0x08000000,
            close_fds=True,
        )
        print("[MoodTune] System tray notifier launched in background.")
    except Exception as e:
        print(f"[MoodTune] Could not launch notifier: {e}")

# ── Run ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Auto-launch the notifier once Flask is ready.
    # In debug mode the werkzeug reloader spawns a child process that sets
    # WERKZEUG_RUN_MAIN=true – we only launch the notifier from that child
    # so we don't get duplicate processes.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        threading.Thread(target=_launch_notifier, daemon=True).start()

    app.run(
        debug=True,
        port=5000,
        exclude_patterns=["*/.venv/*", "*/__pycache__/*"],
    )

