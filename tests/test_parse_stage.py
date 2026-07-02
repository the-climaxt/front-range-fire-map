"""Regression tests for build.py's parse_stage.

Every fixture marked REAL is phrasing that actually appeared on official pages
in June–July 2026 and fooled the previous parser (see AUDIT.md C4). If reality
fools the parser again, freeze the page text here as a new fixture.

Run from _autopublish/:  python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build import parse_stage  # noqa: E402


class TransitionHeadlines(unittest.TestCase):
    """REAL 2026 phrasings the old regex missed entirely (returned None)."""

    def test_wrnf_enters(self):
        self.assertEqual(parse_stage(
            "<h1>White River NF enters Stage 2 Fire Restrictions</h1>"), "Stage 2")

    def test_wrnf_moves_to(self):
        self.assertEqual(parse_stage(
            "White River National Forest Moves to Stage 2 Fire Restrictions June 26"), "Stage 2")

    def test_sanjuan_effective(self):
        self.assertEqual(parse_stage(
            "Stage 2 fire restrictions effective July 1 on the San Juan National Forest"), "Stage 2")

    def test_gmug_move_to(self):
        self.assertEqual(parse_stage(
            "GMUG National Forests Move to Stage 2 Fire Restrictions"), "Stage 2")

    def test_routt_enters(self):
        self.assertEqual(parse_stage(
            "Routt National Forest enters Stage 1 fire restrictions"), "Stage 1")

    def test_under_stage(self):
        self.assertEqual(parse_stage(
            "The forest is currently under Stage 2 fire restrictions."), "Stage 2")

    def test_implements_roman(self):
        # REAL: "Sheriff Roybal Implements Stage II Fire Restrictions"
        self.assertEqual(parse_stage(
            "Sheriff Roybal Implements Stage II Fire Restrictions for El Paso County"), "Stage 2")


class InEffectPhrasings(unittest.TestCase):
    """REAL county-page phrasings (these worked before and must keep working)."""

    def test_jeffco(self):
        self.assertEqual(parse_stage(
            "As of July 2, 2026, a Stage 2 fire ban is in effect in unincorporated Jefferson County"), "Stage 2")

    def test_douglas(self):
        self.assertEqual(parse_stage(
            "STAGE 2 FIRE RESTRICTIONS ARE IN PLACE FOR UNINCORPORATED DOUGLAS COUNTY"), "Stage 2")

    def test_chaffee(self):
        self.assertEqual(parse_stage(
            "Stage 2 Fire Restrictions in effect beginning June 24th for all of unincorporated Chaffee County"), "Stage 2")


class DefinitionalTextMustNotMatch(unittest.TestCase):
    """Explainer/speculative sentences the old regex WRONGLY matched."""

    def test_when_definition(self):
        self.assertIsNone(parse_stage(
            "What are fire restrictions? When Stage 2 fire restrictions are in effect, "
            "the following are prohibited: campfires."))

    def test_speculative_stage3(self):
        # Old parser returned "Stage 3" here because Stage 3 is checked first.
        self.assertEqual(parse_stage(
            "Stage 3 closures may be implemented when conditions worsen. "
            "Currently Stage 1 fire restrictions are in effect."), "Stage 1")

    def test_pure_speculation_alone(self):
        self.assertIsNone(parse_stage(
            "Stage 2 restrictions would be implemented if conditions deteriorate."))


class LiftsAndNone(unittest.TestCase):
    def test_rescinded(self):
        self.assertEqual(parse_stage(
            "The forest has rescinded Stage 1 fire restrictions as of May 28."), "None")

    def test_lifted_generic(self):
        self.assertEqual(parse_stage(
            "Officials lifted fire restrictions across the district."), "None")

    def test_no_restrictions(self):
        self.assertEqual(parse_stage(
            "There are no current fire restrictions on the forest."), "None")

    def test_transition_beats_lift(self):
        # rescind of the OLD stage + entry of the NEW stage -> the new stage wins
        self.assertEqual(parse_stage(
            "The order rescinds Stage 2 restrictions; the forest enters Stage 1 fire restrictions."), "Stage 1")


class UncertainPages(unittest.TestCase):
    def test_no_signal_returns_none_object(self):
        # A page with no restriction language: parser must return None (=
        # "could not tell"), which the builder ships as UNVERIFIED, never fresh.
        self.assertIsNone(parse_stage(
            "Welcome to the Rio Grande National Forest. Know Before You Go. "
            "Food storage order in effect for bear country."))

    def test_empty(self):
        self.assertIsNone(parse_stage(""))

    def test_severest_of_multiple(self):
        # Old + new announcements on one page -> most severe wins (over-warn).
        self.assertEqual(parse_stage(
            "June 19: forest enters Stage 1 fire restrictions. "
            "June 26: forest enters Stage 2 fire restrictions."), "Stage 2")

    def test_html_stripping(self):
        self.assertEqual(parse_stage(
            "<script>var x='stage 3 in effect';</script><p>Forest enters "
            "<b>Stage 1</b> fire restrictions</p>"), "Stage 1")


if __name__ == "__main__":
    unittest.main()
