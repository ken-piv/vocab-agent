#!/usr/bin/env python3
"""Unit tests for vocab_agent.py"""

import json
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

import vocab_agent as va


# ---------------------------------------------------------------------------
# TestLevenshteinDistance
# ---------------------------------------------------------------------------

class TestLevenshteinDistance(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(va.levenshtein("hello", "hello"), 0)

    def test_insertion(self):
        self.assertEqual(va.levenshtein("cat", "cats"), 1)

    def test_deletion(self):
        self.assertEqual(va.levenshtein("cats", "cat"), 1)

    def test_substitution(self):
        self.assertEqual(va.levenshtein("cat", "bat"), 1)

    def test_empty_first(self):
        self.assertEqual(va.levenshtein("", "abc"), 3)

    def test_empty_second(self):
        self.assertEqual(va.levenshtein("abc", ""), 3)

    def test_both_empty(self):
        self.assertEqual(va.levenshtein("", ""), 0)

    def test_symmetry(self):
        self.assertEqual(
            va.levenshtein("kitten", "sitting"),
            va.levenshtein("sitting", "kitten"),
        )

    def test_multi_edit(self):
        self.assertEqual(va.levenshtein("kitten", "sitting"), 3)


# ---------------------------------------------------------------------------
# TestKeywordOverlap
# ---------------------------------------------------------------------------

class TestKeywordOverlap(unittest.TestCase):
    def test_exact_keyword_match(self):
        self.assertTrue(va.keyword_overlap(
            "something lasting forever",
            "lasting for a very long time or forever"
        ))

    def test_no_overlap(self):
        self.assertFalse(va.keyword_overlap(
            "the cat sat on the mat",
            "a quantum physics phenomenon involving entanglement"
        ))

    def test_stopwords_excluded(self):
        # Only stopwords shared should not count
        self.assertFalse(va.keyword_overlap(
            "the is a for on with",
            "this was an at by from"
        ))

    def test_case_insensitive(self):
        self.assertTrue(va.keyword_overlap(
            "PERMANENT fixture",
            "a permanent structure"
        ))

    def test_punctuation_stripping(self):
        self.assertTrue(va.keyword_overlap(
            "lasting, enduring, permanent!",
            "something that is permanent"
        ))

    def test_short_words_excluded(self):
        # Words < 3 chars should not count as matches
        self.assertFalse(va.keyword_overlap("go do be", "go do be"))


# ---------------------------------------------------------------------------
# TestSentenceHeuristics
# ---------------------------------------------------------------------------

class TestSentenceHeuristics(unittest.TestCase):
    def test_word_present_passes(self):
        ok, _ = va.check_sentence_heuristics(
            "The ephemeral beauty of the sunset was breathtaking.",
            "ephemeral",
            []
        )
        self.assertTrue(ok)

    def test_word_missing_fails(self):
        ok, msg = va.check_sentence_heuristics(
            "The beauty of the sunset was breathtaking.",
            "ephemeral",
            []
        )
        self.assertFalse(ok)
        self.assertIn("must contain", msg)

    def test_too_short_fails(self):
        ok, msg = va.check_sentence_heuristics(
            "Very ephemeral thing here.",
            "ephemeral",
            []
        )
        # 4 words - should fail the >= 5 check
        self.assertFalse(ok)
        self.assertIn("longer sentence", msg)

    def test_three_words_fails(self):
        ok, msg = va.check_sentence_heuristics(
            "It is ephemeral.",
            "ephemeral",
            []
        )
        self.assertFalse(ok)
        self.assertIn("longer sentence", msg)

    def test_copied_example_fails(self):
        examples = ["The ephemeral nature of cherry blossoms makes them special."]
        ok, msg = va.check_sentence_heuristics(
            "The ephemeral nature of cherry blossoms makes them special.",
            "ephemeral",
            examples
        )
        self.assertFalse(ok)
        self.assertIn("original", msg)

    def test_original_sentence_passes(self):
        examples = ["The ephemeral nature of cherry blossoms makes them special."]
        ok, _ = va.check_sentence_heuristics(
            "Her ephemeral fame faded quickly after the scandal.",
            "ephemeral",
            examples
        )
        self.assertTrue(ok)

    def test_min_words_boundary(self):
        ok, _ = va.check_sentence_heuristics(
            "The ephemeral joy was fleeting.",
            "ephemeral",
            []
        )
        # 5 words - should pass
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# TestSentenceEvalWithClaude
# ---------------------------------------------------------------------------

class TestSentenceEvalWithClaude(unittest.TestCase):
    @patch("vocab_agent.subprocess.run")
    def test_pass_response(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="PASS Great usage of the word."
        )
        ok, feedback = va.evaluate_sentence_with_claude("test sentence", "word", "meaning")
        self.assertTrue(ok)
        self.assertIn("PASS", feedback)

    @patch("vocab_agent.subprocess.run")
    def test_fail_response(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="FAIL The sentence doesn't demonstrate understanding."
        )
        ok, feedback = va.evaluate_sentence_with_claude("test sentence", "word", "meaning")
        self.assertFalse(ok)
        self.assertIn("FAIL", feedback)

    @patch("vocab_agent.subprocess.run")
    def test_timeout_fallback(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
        ok, feedback = va.evaluate_sentence_with_claude("test sentence", "word", "meaning")
        self.assertTrue(ok)
        self.assertIn("unavailable", feedback.lower())

    @patch("vocab_agent.subprocess.run")
    def test_file_not_found_fallback(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        ok, feedback = va.evaluate_sentence_with_claude("test sentence", "word", "meaning")
        self.assertTrue(ok)
        self.assertIn("unavailable", feedback.lower())

    @patch("vocab_agent.subprocess.run")
    def test_nonzero_exit_fallback(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        ok, feedback = va.evaluate_sentence_with_claude("test sentence", "word", "meaning")
        self.assertTrue(ok)
        self.assertIn("unavailable", feedback.lower())

    @patch("vocab_agent.subprocess.run")
    def test_unparseable_response(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="I'm not sure what to say here."
        )
        ok, feedback = va.evaluate_sentence_with_claude("test sentence", "word", "meaning")
        self.assertTrue(ok)
        self.assertIn("auto-approved", feedback.lower())


# ---------------------------------------------------------------------------
# TestDatabase
# ---------------------------------------------------------------------------

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        va.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_init_db_creates_table(self):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='words_seen'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_is_today_completed_false(self):
        self.assertFalse(va.is_today_completed(self.conn, "2025-01-15"))

    def test_is_today_completed_true(self):
        self.conn.execute(
            "INSERT INTO words_seen (word, date_shown, date_completed, quiz_passed) "
            "VALUES ('test', '2025-01-15', '2025-01-15', 1)"
        )
        self.assertTrue(va.is_today_completed(self.conn, "2025-01-15"))

    def test_get_used_words_empty(self):
        self.assertEqual(va.get_used_words(self.conn), set())

    def test_get_used_words(self):
        self.conn.execute(
            "INSERT INTO words_seen (word, date_shown) VALUES ('alpha', '2025-01-15')"
        )
        self.conn.execute(
            "INSERT INTO words_seen (word, date_shown) VALUES ('beta', '2025-01-16')"
        )
        self.assertEqual(va.get_used_words(self.conn), {"alpha", "beta"})

    def test_save_word_shown(self):
        va.save_word_shown(self.conn, "test", '{"word":"test"}', "2025-01-15")
        row = self.conn.execute("SELECT word, date_shown FROM words_seen").fetchone()
        self.assertEqual(row, ("test", "2025-01-15"))

    def test_save_word_shown_ignore_duplicate(self):
        va.save_word_shown(self.conn, "test", '{"word":"test"}', "2025-01-15")
        va.save_word_shown(self.conn, "test", '{"word":"test"}', "2025-01-16")
        count = self.conn.execute("SELECT COUNT(*) FROM words_seen").fetchone()[0]
        self.assertEqual(count, 1)

    def test_save_notes(self):
        va.save_word_shown(self.conn, "test", '{}', "2025-01-15")
        va.save_notes(self.conn, "test", "my notes about this word")
        row = self.conn.execute("SELECT user_notes FROM words_seen WHERE word='test'").fetchone()
        self.assertEqual(row[0], "my notes about this word")

    def test_save_completion(self):
        va.save_word_shown(self.conn, "test", '{}', "2025-01-15")
        va.save_completion(self.conn, "test", "2025-01-15")
        row = self.conn.execute(
            "SELECT quiz_passed, date_completed, quiz_attempts FROM words_seen WHERE word='test'"
        ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "2025-01-15")
        self.assertEqual(row[2], 1)

    def test_increment_attempts(self):
        va.save_word_shown(self.conn, "test", '{}', "2025-01-15")
        va.increment_attempts(self.conn, "test")
        va.increment_attempts(self.conn, "test")
        row = self.conn.execute(
            "SELECT quiz_attempts FROM words_seen WHERE word='test'"
        ).fetchone()
        self.assertEqual(row[0], 2)

    def test_get_todays_word_none(self):
        self.assertIsNone(va.get_todays_word(self.conn, "2025-01-15"))

    def test_get_todays_word_returns_incomplete(self):
        va.save_word_shown(self.conn, "test", '{"word":"test"}', "2025-01-15")
        result = va.get_todays_word(self.conn, "2025-01-15")
        self.assertIsNotNone(result)
        self.assertEqual(result["word"], "test")

    def test_get_todays_word_skips_completed(self):
        va.save_word_shown(self.conn, "test", '{}', "2025-01-15")
        va.save_completion(self.conn, "test", "2025-01-15")
        self.assertIsNone(va.get_todays_word(self.conn, "2025-01-15"))


# ---------------------------------------------------------------------------
# TestStreakCalculation
# ---------------------------------------------------------------------------

class TestStreakCalculation(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        va.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def _complete(self, word, date):
        self.conn.execute(
            "INSERT INTO words_seen (word, date_shown, date_completed, quiz_passed) "
            "VALUES (?, ?, ?, 1)",
            (word, date, date),
        )
        self.conn.commit()

    def test_empty_db(self):
        self.assertEqual(va.get_streak(self.conn, "2025-01-15"), 0)

    def test_today_only(self):
        self._complete("w1", "2025-01-15")
        self.assertEqual(va.get_streak(self.conn, "2025-01-15"), 1)

    def test_consecutive_days(self):
        self._complete("w1", "2025-01-13")
        self._complete("w2", "2025-01-14")
        self._complete("w3", "2025-01-15")
        self.assertEqual(va.get_streak(self.conn, "2025-01-15"), 3)

    def test_gap_breaks_streak(self):
        self._complete("w1", "2025-01-12")
        # Gap on 2025-01-13
        self._complete("w2", "2025-01-14")
        self._complete("w3", "2025-01-15")
        self.assertEqual(va.get_streak(self.conn, "2025-01-15"), 2)

    def test_today_incomplete_means_zero(self):
        self._complete("w1", "2025-01-14")
        self.assertEqual(va.get_streak(self.conn, "2025-01-15"), 0)

    def test_month_boundary(self):
        self._complete("w1", "2025-01-30")
        self._complete("w2", "2025-01-31")
        self._complete("w3", "2025-02-01")
        self.assertEqual(va.get_streak(self.conn, "2025-02-01"), 3)

    def test_long_streak(self):
        for i in range(10):
            date = f"2025-01-{i + 1:02d}"
            self._complete(f"w{i}", date)
        self.assertEqual(va.get_streak(self.conn, "2025-01-10"), 10)


# ---------------------------------------------------------------------------
# TestWordSelection
# ---------------------------------------------------------------------------

class TestWordSelection(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        va.init_db(self.conn)
        self.sample_words = [
            {"word": "ephemeral", "pos": "adjective", "definition": "lasting a very short time",
             "example": "The ephemeral nature of fame.", "synonyms": ["fleeting", "transient"]},
            {"word": "cogent", "pos": "adjective", "definition": "clear and convincing",
             "example": "A cogent argument.", "synonyms": ["compelling", "persuasive"]},
            {"word": "ubiquitous", "pos": "adjective", "definition": "found everywhere",
             "example": "Smartphones are ubiquitous.", "synonyms": ["omnipresent", "pervasive"]},
        ]

    def tearDown(self):
        self.conn.close()

    @patch("vocab_agent.load_words")
    @patch("vocab_agent.fetch_api_data", return_value=None)
    def test_picks_unused_word(self, mock_api, mock_load):
        mock_load.return_value = self.sample_words
        word_data = va.pick_word(self.conn, "2025-01-15")
        self.assertIn(word_data["word"], {"ephemeral", "cogent", "ubiquitous"})

    @patch("vocab_agent.load_words")
    @patch("vocab_agent.fetch_api_data", return_value=None)
    def test_no_repeats(self, mock_api, mock_load):
        mock_load.return_value = self.sample_words
        va.save_word_shown(self.conn, "ephemeral", '{}', "2025-01-14")
        va.save_word_shown(self.conn, "cogent", '{}', "2025-01-13")
        word_data = va.pick_word(self.conn, "2025-01-15")
        self.assertEqual(word_data["word"], "ubiquitous")

    def test_resumes_incomplete_word(self):
        api_data = json.dumps({
            "word": "ephemeral",
            "phonetic": "",
            "pos": "adjective",
            "definitions": [{"definition": "lasting a very short time"}],
            "synonyms": ["fleeting"],
        })
        va.save_word_shown(self.conn, "ephemeral", api_data, "2025-01-15")
        word_data = va.pick_word(self.conn, "2025-01-15")
        self.assertEqual(word_data["word"], "ephemeral")

    @patch("vocab_agent.load_words")
    @patch("vocab_agent.fetch_api_data", return_value=None)
    def test_pool_exhausted(self, mock_api, mock_load):
        mock_load.return_value = self.sample_words
        for w in self.sample_words:
            va.save_word_shown(self.conn, w["word"], '{}', "2025-01-01")
        with self.assertRaises(SystemExit):
            va.pick_word(self.conn, "2025-01-15")


# ---------------------------------------------------------------------------
# TestFormatApiData
# ---------------------------------------------------------------------------

class TestFormatApiData(unittest.TestCase):
    """Tests for format_api_data, especially flat->nested definition conversion."""

    def test_flat_fallback_produces_definitions_list(self):
        """Bug: words.json has flat 'definition' string but display expects
        'definitions' list of dicts. format_api_data must convert."""
        fallback = {
            "word": "ephemeral",
            "pos": "adjective",
            "definition": "lasting a very short time",
            "example": "The ephemeral nature of fame.",
            "synonyms": ["fleeting", "transient"],
        }
        result = va.format_api_data(None, fallback)
        self.assertIsInstance(result["definitions"], list)
        self.assertGreater(len(result["definitions"]), 0, "definitions must not be empty")
        self.assertEqual(result["definitions"][0]["definition"], "lasting a very short time")
        self.assertEqual(result["definitions"][0]["example"], "The ephemeral nature of fame.")

    def test_flat_fallback_no_example(self):
        """Fallback with definition but no example should still work."""
        fallback = {
            "word": "cogent",
            "pos": "adjective",
            "definition": "clear and convincing",
            "synonyms": ["compelling"],
        }
        result = va.format_api_data(None, fallback)
        self.assertEqual(len(result["definitions"]), 1)
        self.assertEqual(result["definitions"][0]["definition"], "clear and convincing")

    def test_api_data_overrides_fallback(self):
        """When API data is available, it should override the fallback definitions."""
        fallback = {
            "word": "test",
            "pos": "noun",
            "definition": "fallback def",
            "synonyms": [],
        }
        api_entry = {
            "word": "test",
            "meanings": [{
                "partOfSpeech": "noun",
                "definitions": [
                    {"definition": "api definition", "example": "api example"}
                ],
                "synonyms": ["trial"],
            }],
        }
        result = va.format_api_data(api_entry, fallback)
        self.assertEqual(result["definitions"][0]["definition"], "api definition")

    def test_pick_word_returns_nonempty_definitions(self):
        """End-to-end: pick_word with no API should still have definitions."""
        conn = sqlite3.connect(":memory:")
        va.init_db(conn)
        sample = [
            {"word": "ephemeral", "pos": "adjective",
             "definition": "lasting a very short time",
             "example": "The ephemeral nature of fame.",
             "synonyms": ["fleeting", "transient"]},
        ]
        with patch("vocab_agent.load_words", return_value=sample), \
             patch("vocab_agent.fetch_api_data", return_value=None):
            word_data = va.pick_word(conn, "2025-01-15")
        self.assertGreater(len(word_data.get("definitions", [])), 0,
                           "definitions must not be empty when API is unavailable")
        conn.close()


    def test_resume_stale_db_with_empty_definitions(self):
        """Bug #2: pick_word resume path returns cached api_data directly,
        bypassing format_api_data. If the DB has stale data with empty
        definitions (written before the flat->nested fix), definitions
        are still empty on resume."""
        conn = sqlite3.connect(":memory:")
        va.init_db(conn)
        stale_api_data = json.dumps({
            "word": "ephemeral",
            "phonetic": "",
            "pos": "adjective",
            "definitions": [],
            "synonyms": ["fleeting"],
        })
        va.save_word_shown(conn, "ephemeral", stale_api_data, "2025-01-15")
        words_json = [
            {"word": "ephemeral", "pos": "adjective",
             "definition": "lasting a very short time",
             "example": "The ephemeral nature of fame.",
             "synonyms": ["fleeting", "transient"]},
        ]
        with patch("vocab_agent.load_words", return_value=words_json):
            word_data = va.pick_word(conn, "2025-01-15")
        self.assertGreater(len(word_data.get("definitions", [])), 0,
                           "resume path must not return empty definitions from stale cache")
        self.assertEqual(word_data["definitions"][0]["definition"],
                         "lasting a very short time")
        conn.close()


if __name__ == "__main__":
    unittest.main()
