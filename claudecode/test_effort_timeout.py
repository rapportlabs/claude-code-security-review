import os
import pytest
from unittest.mock import patch

from claudecode.github_action_audit import (
    _get_claude_timeout_minutes,
    _get_effort_level,
)


class TestGetClaudeTimeoutMinutes:
    def test_reads_env_var(self):
        with patch.dict(os.environ, {'CLAUDE_TIMEOUT': '12'}):
            assert _get_claude_timeout_minutes() == 12

    def test_default_when_unset(self):
        env = os.environ.copy()
        env.pop('CLAUDE_TIMEOUT', None)
        with patch.dict(os.environ, env, clear=True):
            assert _get_claude_timeout_minutes() == 15

    def test_invalid_non_numeric(self):
        with patch.dict(os.environ, {'CLAUDE_TIMEOUT': 'abc'}):
            assert _get_claude_timeout_minutes() == 15

    def test_invalid_zero(self):
        with patch.dict(os.environ, {'CLAUDE_TIMEOUT': '0'}):
            assert _get_claude_timeout_minutes() == 15

    def test_invalid_negative(self):
        with patch.dict(os.environ, {'CLAUDE_TIMEOUT': '-5'}):
            assert _get_claude_timeout_minutes() == 15

    def test_large_value_accepted(self):
        with patch.dict(os.environ, {'CLAUDE_TIMEOUT': '30'}):
            assert _get_claude_timeout_minutes() == 30


class TestGetEffortLevel:
    def test_reads_valid_low(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'low'}):
            assert _get_effort_level() == 'low'

    def test_reads_valid_medium(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'medium'}):
            assert _get_effort_level() == 'medium'

    def test_reads_valid_high(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'high'}):
            assert _get_effort_level() == 'high'

    def test_reads_valid_xhigh(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'xhigh'}):
            assert _get_effort_level() == 'xhigh'

    def test_reads_valid_max(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'max'}):
            assert _get_effort_level() == 'max'

    def test_none_when_unset(self):
        env = os.environ.copy()
        env.pop('CLAUDE_EFFORT', None)
        with patch.dict(os.environ, env, clear=True):
            assert _get_effort_level() is None

    def test_none_when_empty(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': ''}):
            assert _get_effort_level() is None

    def test_none_when_invalid(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'turbo'}):
            assert _get_effort_level() is None

    def test_case_insensitive(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': 'LOW'}):
            assert _get_effort_level() == 'low'

    def test_whitespace_trimmed(self):
        with patch.dict(os.environ, {'CLAUDE_EFFORT': '  medium  '}):
            assert _get_effort_level() == 'medium'
