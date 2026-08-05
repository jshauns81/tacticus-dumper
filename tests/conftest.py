import os
import tempfile


_TEST_DATA_DIR = tempfile.TemporaryDirectory(prefix="tacticus-tests-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR.name
