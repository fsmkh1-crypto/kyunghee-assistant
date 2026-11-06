import os
from pathlib import Path
import unittest
from unittest.mock import patch

from desktop_ai_review import REVIEW_MUTEX, ReviewSingleInstance, review_appdata


class ReviewLauncherTests(unittest.TestCase):
    def test_prefers_localappdata_and_never_reuses_normal_appdata(self):
        values = {"LOCALAPPDATA": "/review-local", "APPDATA": "/normal-data", "TEMP": "/temporary"}
        self.assertEqual(review_appdata(values), Path("/review-local/KyungheeTimer_AI_Review"))
        self.assertEqual(values["APPDATA"], "/normal-data")

    def test_missing_localappdata_uses_separate_temp_folder(self):
        self.assertEqual(review_appdata({"TEMP": "/temporary"}),
                         Path("/temporary/KyungheeTimer_AI_Review"))
        with patch("desktop_ai_review.tempfile.gettempdir", return_value="/fallback-temp"):
            self.assertEqual(review_appdata({}), Path("/fallback-temp/KyungheeTimer_AI_Review"))

    def test_review_mutex_differs_from_the_stable_instance(self):
        self.assertEqual(REVIEW_MUTEX, "Local\\KyungheeTimerAIReviewSingleton")
        self.assertNotEqual(REVIEW_MUTEX, "Local\\KyungheeAssistantSingleton")
        if os.name != "nt":
            self.assertTrue(ReviewSingleInstance().acquire())


if __name__ == "__main__":
    unittest.main()
