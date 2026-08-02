#write tests that feed broken data into a dummy database, and see how well the program can correctly
#identify what must be erased, incremented, or modified.
import pytest
import test_utilities as util
util.set_path_for_extract_modules()