#!/usr/bin/env python3
"""Interactive vocabulary learning agent with daily word practice and quizzes."""

import json
import sqlite3
import urllib.request
import readline  # noqa: F401 — imported for input() history side-effect
import subprocess
import signal
import os
import sys
import time
import datetime
import random
import re
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VOCAB_DIR = Path.home() / "vocab-agent"
DB_PATH = VOCAB_DIR / "vocab.db"
WORDS_FILE = VOCAB_DIR / "words.json"

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
MAGENTA = "\033[35m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS words_seen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            date_shown TEXT NOT NULL,
            date_completed TEXT,
            api_data TEXT,
            user_notes TEXT DEFAULT '',
            quiz_attempts INTEGER DEFAULT 0,
            quiz_passed INTEGER DEFAULT 0
        );
    """)
    conn.commit()


def is_today_completed(conn, today=None):
    today = today or datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT 1 FROM words_seen WHERE date_completed = ? LIMIT 1", (today,)
    ).fetchone()
    return row is not None


def get_used_words(conn):
    rows = conn.execute("SELECT word FROM words_seen").fetchall()
    return {r[0] for r in rows}


def get_todays_word(conn, today=None):
    today = today or datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT word, date_shown, date_completed, api_data, user_notes, "
        "quiz_attempts, quiz_passed FROM words_seen "
        "WHERE date_shown = ? AND quiz_passed = 0",
        (today,),
    ).fetchone()
    if row is None:
        return None
    return {
        "word": row[0],
        "date_shown": row[1],
        "date_completed": row[2],
        "api_data": row[3],
        "user_notes": row[4],
        "quiz_attempts": row[5],
        "quiz_passed": row[6],
    }


def save_word_shown(conn, word, api_data_json, today=None):
    today = today or datetime.date.today().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO words_seen (word, date_shown, api_data) VALUES (?, ?, ?)",
        (word, today, api_data_json),
    )
    conn.commit()


def save_notes(conn, word, notes):
    conn.execute("UPDATE words_seen SET user_notes = ? WHERE word = ?", (notes, word))
    conn.commit()


def save_completion(conn, word, today=None):
    today = today or datetime.date.today().isoformat()
    conn.execute(
        "UPDATE words_seen SET quiz_passed = 1, date_completed = ?, "
        "quiz_attempts = quiz_attempts + 1 WHERE word = ?",
        (today, word),
    )
    conn.commit()


def increment_attempts(conn, word):
    conn.execute(
        "UPDATE words_seen SET quiz_attempts = quiz_attempts + 1 WHERE word = ?",
        (word,),
    )
    conn.commit()


def get_streak(conn, today=None):
    today = today or datetime.date.today().isoformat()
    # The today value is an ISO date string we control, safe to interpolate.
    query = f"""
        WITH RECURSIVE
        completed_dates(d) AS (
            SELECT DISTINCT date_completed FROM words_seen WHERE date_completed IS NOT NULL
        ),
        walk(day, steps) AS (
            SELECT date('{today}'), 0
            WHERE date('{today}') IN (SELECT d FROM completed_dates)
            UNION ALL
            SELECT date(walk.day, '-1 day'), walk.steps + 1
            FROM walk
            WHERE date(walk.day, '-1 day') IN (SELECT d FROM completed_dates)
        )
        SELECT COALESCE(MAX(steps) + 1, 0) FROM walk;
    """
    row = conn.execute(query).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Pure utility functions
# ---------------------------------------------------------------------------


def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev[j + 1] + 1
            delete = curr[j] + 1
            replace = prev[j] + (0 if c1 == c2 else 1)
            curr.append(min(insert, delete, replace))
        prev = curr
    return prev[-1]


def get_stopwords():
    return {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "it", "its", "this",
        "that", "these", "those", "i", "me", "my", "we", "our", "you", "your",
        "he", "him", "his", "she", "her", "they", "them", "their", "what",
        "which", "who", "whom", "when", "where", "why", "how", "all", "each",
        "every", "both", "few", "more", "most", "other", "some", "such", "no",
        "not", "only", "same", "so", "than", "too", "very", "just", "about",
        "also", "and", "but", "or", "if", "because", "until", "while", "up",
        "down",
    }


def keyword_overlap(user_text, reference_text):
    stopwords = get_stopwords()
    tokenize = lambda t: {w for w in re.split(r"[^a-zA-Z]+", t.lower()) if len(w) >= 3 and w not in stopwords}
    user_tokens = tokenize(user_text)
    ref_tokens = tokenize(reference_text)
    return len(user_tokens & ref_tokens) >= 1


def check_sentence_heuristics(sentence, word, examples):
    if word.lower() not in sentence.lower():
        return False, "Your sentence must contain the word."
    if len(sentence.split()) < 5:
        return False, "Please write a longer sentence (at least 5 words)."
    for ex in examples:
        if ex.lower() in sentence.lower() or sentence.lower() in ex.lower():
            return False, "Please write your own original sentence."
    return True, ""


def evaluate_sentence_with_claude(sentence, word, definition):
    prompt_text = (
        f'You are evaluating whether a sentence correctly uses the word "{word}" '
        f"(meaning: {definition}).\n\n"
        f'Sentence: "{sentence}"\n\n'
        "Does this sentence demonstrate understanding of the word's meaning? "
        "Be lenient - accept creative or informal usage as long as the meaning "
        "is roughly correct.\n\n"
        "Reply with exactly one line: PASS or FAIL followed by a brief explanation."
    )
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet", "--max-budget-usd", "0.05"],
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return True, "Auto-approved (Claude unavailable)."
        output = result.stdout.strip()
        first_line = output.split("\n")[0]
        if first_line.upper().startswith("PASS"):
            return True, first_line
        elif first_line.upper().startswith("FAIL"):
            return False, first_line
        return True, "Auto-approved (could not parse response)."
    except FileNotFoundError:
        return True, "Auto-approved (Claude unavailable)."
    except subprocess.TimeoutExpired:
        return True, "Auto-approved (Claude unavailable)."


# ---------------------------------------------------------------------------
# Word selection
# ---------------------------------------------------------------------------


def load_words():
    with open(WORDS_FILE, "r") as f:
        return json.load(f)


def fetch_api_data(word):
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return data[0] if data else None
    except Exception:
        return None


def format_api_data(api_entry, fallback):
    word = fallback.get("word", "")
    phonetic = fallback.get("phonetic", "")
    pos = fallback.get("pos", "")
    definitions = fallback.get("definitions", [])
    if not definitions and fallback.get("definition"):
        entry = {"definition": fallback["definition"]}
        if fallback.get("example"):
            entry["example"] = fallback["example"]
        definitions = [entry]
    synonyms = fallback.get("synonyms", [])

    if api_entry:
        word = api_entry.get("word", word)
        phonetic = api_entry.get("phonetic", "") or phonetic
        if not phonetic:
            for ph in api_entry.get("phonetics", []):
                if ph.get("text"):
                    phonetic = ph["text"]
                    break

        for meaning in api_entry.get("meanings", []):
            if not pos:
                pos = meaning.get("partOfSpeech", pos)
            api_defs = []
            for d in meaning.get("definitions", []):
                entry = {"definition": d.get("definition", "")}
                if d.get("example"):
                    entry["example"] = d["example"]
                api_defs.append(entry)
            if api_defs:
                definitions = api_defs

            api_syns = meaning.get("synonyms", [])
            if api_syns:
                synonyms = api_syns

    return {
        "word": word,
        "phonetic": phonetic,
        "pos": pos,
        "definitions": definitions,
        "synonyms": synonyms,
    }


def pick_word(conn, today=None):
    today = today or datetime.date.today().isoformat()

    existing = get_todays_word(conn, today)
    if existing:
        api_data = json.loads(existing["api_data"]) if existing["api_data"] else {}
        if not api_data.get("definitions"):
            all_words = load_words()
            match = next((w for w in all_words if w["word"] == api_data.get("word")), None)
            if match:
                api_data = format_api_data(None, match)
                conn.execute("UPDATE words_seen SET api_data = ? WHERE word = ?",
                             (json.dumps(api_data), api_data["word"]))
                conn.commit()
        return api_data

    all_words = load_words()
    used = get_used_words(conn)
    available = [w for w in all_words if w.get("word") not in used]

    if not available:
        raise SystemExit("You've learned all the words! Impressive.")

    chosen = random.choice(available)
    api_entry = fetch_api_data(chosen["word"])
    word_data = format_api_data(api_entry, chosen)
    api_data_json = json.dumps(word_data)
    save_word_shown(conn, word_data["word"], api_data_json, today)
    return word_data


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------


def clear_screen():
    print("\033[2J\033[H", end="")


def show_header(word, streak):
    width = 50
    print(f"\n{CYAN}{'=' * width}{RESET}")
    print(f"{CYAN}  {BOLD}VOCAB AGENT{RESET}{CYAN}  |  {YELLOW}Streak: {streak} day{'s' if streak != 1 else ''}{RESET}")
    print(f"{CYAN}{'=' * width}{RESET}")
    print(f"  Today's word: {BOLD}{MAGENTA}{word}{RESET}")
    print(f"{CYAN}{'-' * width}{RESET}\n")


def show_word_card(word_data):
    word = word_data["word"]
    phonetic = word_data.get("phonetic", "")
    pos = word_data.get("pos", "")
    definitions = word_data.get("definitions", [])
    synonyms = word_data.get("synonyms", [])

    print(f"  {BOLD}{MAGENTA}{word}{RESET}", end="")
    if phonetic:
        print(f"  {DIM}{phonetic}{RESET}", end="")
    if pos:
        print(f"  {CYAN}({pos}){RESET}", end="")
    print("\n")

    for i, d in enumerate(definitions, 1):
        defn = d.get("definition", "")
        wrapped = textwrap.fill(defn, width=60, initial_indent="     ", subsequent_indent="     ")
        print(f"  {YELLOW}{i}.{RESET}{wrapped.lstrip()}")
        example = d.get("example", "")
        if example:
            print(f"     {DIM}\"{example}\"{RESET}")
        print()

    if synonyms:
        syn_str = ", ".join(synonyms[:6])
        print(f"  {GREEN}Synonyms:{RESET} {syn_str}\n")


def show_victory(word, streak):
    print()
    print(f"  {GREEN}{'*' * 44}{RESET}")
    print(f"  {GREEN}*                                          *{RESET}")
    print(f"  {GREEN}*   {BOLD}Congratulations!{RESET}{GREEN}                      *{RESET}")
    print(f"  {GREEN}*   You mastered: {BOLD}{word:<23}{RESET}{GREEN} *{RESET}")
    print(f"  {GREEN}*   Current streak: {BOLD}{streak} day{'s' if streak != 1 else '':<18}{RESET}{GREEN}*{RESET}")
    print(f"  {GREEN}*                                          *{RESET}")
    print(f"  {GREEN}*   Come back tomorrow for a new word!     *{RESET}")
    print(f"  {GREEN}*                                          *{RESET}")
    print(f"  {GREEN}{'*' * 44}{RESET}")
    print()


# ---------------------------------------------------------------------------
# Interactive phases
# ---------------------------------------------------------------------------


def safe_input(prompt=""):
    try:
        return input(prompt)
    except EOFError:
        print()
        raise SystemExit(0)


def phase_learn(word_data):
    show_word_card(word_data)
    print(f"  {DIM}Take a moment to read and absorb. Press Enter when ready to take notes.{RESET}")
    safe_input()


def phase_notes(conn, word, word_data):
    print(f"\n  {BOLD}Notes Phase{RESET}")
    print(f"  {DIM}Think about: mnemonics, personal associations, similar words, when you'd use it{RESET}\n")

    while True:
        notes = safe_input(f"  {CYAN}Your notes:{RESET} ").strip()
        if len(notes.split()) >= 5:
            save_notes(conn, word, notes)
            print(f"  {GREEN}Notes saved.{RESET}\n")
            break
        print(f"  {YELLOW}Please write at least 5 words in your notes.{RESET}")


def recall_quiz(word, definition):
    print(f"\n  {BOLD}Quiz Part A: Recall{RESET}")
    wrapped = textwrap.fill(definition, width=60, initial_indent="  ", subsequent_indent="  ")
    print(f"  {DIM}Definition:{RESET}")
    print(f"{wrapped}")
    print(f"  {DIM}Type the word that matches this definition.{RESET}\n")

    failures = 0
    while True:
        answer = safe_input(f"  {CYAN}Word:{RESET} ").strip()
        if answer.lower() == word.lower():
            print(f"  {GREEN}Correct!{RESET}")
            return True

        failures += 1
        dist = levenshtein(answer.lower(), word.lower())
        if dist <= 2 and answer:
            print(f"  {YELLOW}Close! Check your spelling.{RESET}")
        elif failures >= 5:
            print(f"  {RED}The word was: {BOLD}{word}{RESET}")
            print(f"  {DIM}Type it below to confirm.{RESET}")
            while True:
                confirm = safe_input(f"  {CYAN}Type it:{RESET} ").strip()
                if confirm.lower() == word.lower():
                    print(f"  {GREEN}Got it.{RESET}")
                    return True
                print(f"  {YELLOW}Try again. The word is: {word}{RESET}")
        elif failures >= 3:
            hint = word[0] + "_" * (len(word) - 1)
            print(f"  {YELLOW}Hint: {hint}{RESET}")
        else:
            print(f"  {RED}Not quite. Try again.{RESET}")


def define_quiz(word, definitions):
    print(f"\n  {BOLD}Quiz Part B: Define{RESET}")
    print(f"  {DIM}Define the word:{RESET} {BOLD}{MAGENTA}{word}{RESET}\n")

    failures = 0
    all_def_text = " ".join(d.get("definition", "") for d in definitions)

    while True:
        answer = safe_input(f"  {CYAN}Your definition:{RESET} ").strip()

        if len(answer) < 15:
            print(f"  {YELLOW}Please provide a more detailed definition (at least 15 characters).{RESET}")
            continue
        if word.lower() in answer.lower():
            print(f"  {YELLOW}Try defining it without using the word itself.{RESET}")
            continue
        if keyword_overlap(answer, all_def_text):
            print(f"  {GREEN}Good definition!{RESET}")
            return True

        failures += 1
        if failures >= 3:
            print(f"\n  {YELLOW}Here are the definitions again:{RESET}")
            for i, d in enumerate(definitions, 1):
                print(f"  {i}. {d.get('definition', '')}")
            print(f"\n  {DIM}Try rephrasing one of these in your own words.{RESET}\n")
            failures = 0
        else:
            print(f"  {YELLOW}Not quite. Try to capture the core meaning.{RESET}")


def sentence_quiz(word, definition, examples):
    print(f"\n  {BOLD}Quiz Part C: Use It{RESET}")
    print(f"  {DIM}Write a sentence using the word:{RESET} {BOLD}{MAGENTA}{word}{RESET}\n")

    while True:
        sentence = safe_input(f"  {CYAN}Sentence:{RESET} ").strip()
        if not sentence:
            continue

        ok, msg = check_sentence_heuristics(sentence, word, examples)
        if not ok:
            print(f"  {YELLOW}{msg}{RESET}")
            continue

        ok, feedback = evaluate_sentence_with_claude(sentence, word, definition)
        if ok:
            print(f"  {GREEN}{feedback}{RESET}")
            return True
        else:
            print(f"  {RED}{feedback}{RESET}")
            print(f"  {DIM}Try again with a different sentence.{RESET}")


def phase_quiz(conn, word, word_data):
    definitions = word_data.get("definitions", [])
    primary_def = definitions[0].get("definition", "") if definitions else ""
    examples = [d.get("example", "") for d in definitions if d.get("example")]

    print(f"\n  {BOLD}{'=' * 40}{RESET}")
    print(f"  {BOLD}QUIZ TIME{RESET}")
    print(f"  {BOLD}{'=' * 40}{RESET}")

    recall_quiz(word, primary_def)
    define_quiz(word, definitions)
    sentence_quiz(word, primary_def, examples)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Ctrl+C protection: require 3 presses within 2 seconds to quit.
    sigint_times = []

    def sigint_handler(signum, frame):
        now = time.time()
        sigint_times.append(now)
        # Keep only the last 3 timestamps
        while len(sigint_times) > 3:
            sigint_times.pop(0)
        if len(sigint_times) >= 3 and (sigint_times[-1] - sigint_times[-3]) < 2.0:
            print(f"\n{RED}Force quitting.{RESET}")
            raise SystemExit(1)
        print(f"\n  {YELLOW}Press Ctrl+C 3 times quickly to force quit{RESET}")

    signal.signal(signal.SIGINT, sigint_handler)

    VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()

    with sqlite3.connect(str(DB_PATH)) as conn:
        init_db(conn)

        if is_today_completed(conn, today):
            streak = get_streak(conn, today)
            clear_screen()
            print(f"\n  {GREEN}Already completed today!{RESET}")
            print(f"  {YELLOW}Current streak: {streak} day{'s' if streak != 1 else ''}{RESET}")
            print(f"  {DIM}Come back tomorrow for a new word.{RESET}\n")
            return

        word_data = pick_word(conn, today)
        word = word_data["word"]
        streak = get_streak(conn, today)

        clear_screen()
        show_header(word, streak)

        phase_learn(word_data)
        phase_notes(conn, word, word_data)

        passed = False
        while not passed:
            passed = phase_quiz(conn, word, word_data)
            if not passed:
                increment_attempts(conn, word)

        save_completion(conn, word, today)

        stamp = VOCAB_DIR / f".done-{today}"
        stamp.touch()

        streak = get_streak(conn, today)
        show_victory(word, streak)


if __name__ == "__main__":
    main()
