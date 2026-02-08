# Vocab Agent

A daily vocabulary trainer that launches when you open your laptop, teaches you a new word, and quizzes you until you prove you know it.

One word per day. No skipping. Streaks tracked.

## How It Works

1. **Learn** — A word card appears with definitions, examples, and synonyms
2. **Notes** — Write your own notes (mnemonics, associations, whatever helps)
3. **Quiz** — Three parts:
   - Recall the word from its definition
   - Define the word in your own words
   - Use it in an original sentence (evaluated by Claude if available)

Complete the quiz and you're done for the day. Come back tomorrow.

## Install

Requires macOS and Python 3.

```bash
git clone https://github.com/kennedypivnick/vocab-agent.git ~/vocab-agent
bash ~/vocab-agent/install.sh
```

The installer sets up:
- `vocab` command available in any terminal
- Automatic launch on lid open (via SleepWatcher + Homebrew)
- Fallback triggers at 7, 8, 9 AM (via LaunchAgent)
- Shell hook for new terminal windows

## Usage

```bash
vocab          # Launch manually
```

Or just open your laptop between 5 AM and noon. It finds you.

## Uninstall

```bash
bash ~/vocab-agent/uninstall.sh
```

## How It's Built

- Python standard library only. Zero pip installs.
- 500 curated words with offline definitions
- Optional API enrichment from dictionaryapi.dev
- Optional Claude evaluation for sentence quiz (falls back to heuristics)
- SQLite for progress tracking, streaks computed via recursive CTE
- Three-layer wake detection: SleepWatcher, LaunchAgent, shell hook
- Idempotent gatekeeper prevents duplicate launches

## Tests

```bash
python3 ~/vocab-agent/test_vocab_agent.py
```

## Support This Project

If you find this useful, send a tip on Venmo: **@kennedy-pivnick**
