"""Append-only notices retain supported local and GigaChat request shapes."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from ouroboros.llm import LLMClient
from ouroboros.loop_messages import _append_or_merge_user_content


