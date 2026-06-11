import unittest

from radar.juniors import looks_junior


class TestLooksJunior(unittest.TestCase):
    def test_explicit_junior_titles(self):
        for title in [
            "Software Engineering Intern",
            "Graduate Software Engineer",
            "Junior Product Designer",
            "Trainee Accountant",
            "Apprentice Mechanic",
            "Entry-Level Sales Development Rep",
            "Entry level analyst",
            "Industrial Placement Student",
            "New Grad Backend Engineer",
        ]:
            self.assertTrue(looks_junior(title), title)

    def test_associate_and_analyst_without_seniority(self):
        for title in [
            "Lab Operations Associate",
            "Climate Data Analyst",
            "Operations Analyst",
        ]:
            self.assertTrue(looks_junior(title), title)

    def test_seniority_blocks_the_maybe_words(self):
        for title in [
            "Associate Director",
            "Senior Analyst",
            "Principal Data Analyst",
            "Lead Research Associate",
            "Staff Analyst",
        ]:
            self.assertFalse(looks_junior(title), title)

    def test_plain_roles_are_not_flagged(self):
        for title in [
            "Software Engineer",
            "Founding Engineer",
            "Growth Marketer",
            "Full Stack Engineer",
            "Specialist Nurse (Menopause)",
            "Founding Account Executive",
            "Regulatory Affairs Lead",
            "Embedded Software Engineer",
        ]:
            self.assertFalse(looks_junior(title), title)

    def test_word_boundaries_not_substrings(self):
        # "grad" must not match inside other words.
        self.assertFalse(looks_junior("Photography Degraded Image Specialist"))
        self.assertFalse(looks_junior("Integration Engineer"))

    def test_empty_and_none(self):
        self.assertFalse(looks_junior(""))
        self.assertFalse(looks_junior(None))


if __name__ == "__main__":
    unittest.main()
