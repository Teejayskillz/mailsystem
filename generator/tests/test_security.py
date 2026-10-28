from django.test import TestCase

from generator.models import Throttle
from generator.services.security import RateLimiter


class RateLimiterTests(TestCase):
    def test_allows_up_to_the_limit_then_blocks(self):
        results = [RateLimiter.hit("test", "key", 3, 60)[0] for _ in range(4)]
        self.assertEqual(results, [True, True, True, False])

    def test_returns_retry_after_when_blocked(self):
        for _ in range(2):
            RateLimiter.hit("test2", "key", 2, 60)

        allowed, retry_after = RateLimiter.hit("test2", "key", 2, 60)

        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, 60)

    def test_keys_are_isolated(self):
        for _ in range(2):
            RateLimiter.hit("test3", "a", 2, 60)

        allowed, _ = RateLimiter.hit("test3", "b", 2, 60)
        self.assertTrue(allowed)

    def test_counter_row_is_created(self):
        RateLimiter.hit("test4", "key", 5, 60)
        self.assertEqual(Throttle.objects.filter(bucket="test4").count(), 1)
