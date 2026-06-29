"""Remote-role detection. The flag is judged from the posting text only,
so the bias is towards missing a remote role rather than mislabelling an
on-site one."""

import unittest

from radar import remote


class TestRemote(unittest.TestCase):
    def test_plain_remote_location(self):
        self.assertTrue(remote.looks_remote("Remote", "Software Engineer"))

    def test_remote_in_title(self):
        self.assertTrue(remote.looks_remote("London", "Remote Sales Associate"))

    def test_remote_variants(self):
        for text in ("Remote-first", "Fully remote", "Work from home",
                     "WFH", "Anywhere"):
            self.assertTrue(remote.looks_remote(text, None), text)

    def test_distributed_systems_is_not_remote(self):
        self.assertFalse(remote.looks_remote("London",
                                             "Distributed Systems Engineer"))

    def test_on_site_is_not_remote(self):
        self.assertFalse(remote.looks_remote("London", "Lab Technician"))

    def test_hybrid_is_not_flagged_remote(self):
        self.assertFalse(remote.looks_remote("Hybrid, Manchester", "Analyst"))

    def test_negations_are_not_remote(self):
        self.assertFalse(remote.looks_remote("On-site only", "Engineer"))
        self.assertFalse(remote.looks_remote("Office-based", "Engineer"))

    def test_does_not_match_inside_words(self):
        self.assertFalse(remote.looks_remote("Remoteness researcher", None))
        self.assertFalse(remote.looks_remote("a wfhx role", None))

    def test_empty(self):
        self.assertFalse(remote.looks_remote(None, None))
        self.assertFalse(remote.looks_remote("", ""))


if __name__ == "__main__":
    unittest.main()