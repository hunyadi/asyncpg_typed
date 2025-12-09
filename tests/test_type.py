"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import unittest
from typing import Optional, Union

from asyncpg_typed import get_required_type, is_optional_type


class TestType(unittest.TestCase):
    def test_optional(self) -> None:
        self.assertTrue(is_optional_type(int | None))
        self.assertTrue(is_optional_type(int | str | None))
        self.assertTrue(is_optional_type(Optional[int]))
        self.assertTrue(is_optional_type(Union[int, str, None]))
        self.assertFalse(is_optional_type(int))
        self.assertFalse(is_optional_type(list[int]))

    def test_required(self) -> None:
        self.assertEqual(get_required_type(int | None), int)
        self.assertEqual(get_required_type(int | str | None), int | str)
        self.assertEqual(get_required_type(Optional[int]), int)
        self.assertEqual(get_required_type(Union[int, str, None]), int | str)


if __name__ == "__main__":
    unittest.main()
