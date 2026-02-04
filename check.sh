#!/usr/bin/env sh
#
# Type-safe queries for asyncpg.
#
# Copyright 2025-2026, Levente Hunyadi
# https://github.com/hunyadi/asyncpg_typed

set -e
PYTHON_EXECUTABLE=${PYTHON:-python3}

$PYTHON_EXECUTABLE -m ruff check
$PYTHON_EXECUTABLE -m ruff format --check
$PYTHON_EXECUTABLE -m mypy asyncpg_typed
$PYTHON_EXECUTABLE -m mypy tests

$PYTHON_EXECUTABLE -m unittest discover

$PYTHON_EXECUTABLE -m ruff check
$PYTHON_EXECUTABLE -m ruff format
$PYTHON_EXECUTABLE -m mypy asyncpg_typed
$PYTHON_EXECUTABLE -m mypy tests

rm tests/sample.py
