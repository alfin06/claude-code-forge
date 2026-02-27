import sys
import os
from mle.utils import LanceDBMemory

# Mock get_config to simulate config loading
import mle.utils

def mock_get_config(path):
    # Simulate a config that is None or missing "platform" key to reproduce the bug
    return None

# Patch the get_config function temporarily
original_get_config = mle.utils.get_config
mle.utils.get_config = mock_get_config


try:
    # This should fail on buggy version due to NoneType subscript error
    mem = LanceDBMemory(os.getcwd())
    # If we reach here, error did not occur, so fail test
    assert False, "Expected TypeError due to NoneType subscript, but no error was raised"
except TypeError as e:
    # Confirm the error message references NoneType subscript
    assert "NoneType" in str(e)
finally:
    # Restore the original get_config
    mle.utils.get_config = original_get_config


# Now test fixed behavior by mocking get_config to a valid config dict

def mock_get_config_fixed(path):
    return {"platform": "OpenAI", "api_key": "fake_key"}

mle.utils.get_config = mock_get_config_fixed

try:
    mem = LanceDBMemory(os.getcwd())
    assert mem.text_embedding is not None
except Exception as e:
    assert False, f"Did not expect an exception on fixed version, but got: {e}"
finally:
    mle.utils.get_config = original_get_config


sys.exit(0)
