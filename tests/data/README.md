# Test data

`astronaut.jpg` is derived from the public-domain NASA portrait of astronaut
Eileen Collins as distributed with scikit-image (`skimage.data.astronaut`).
It is used solely as a real-face fixture for automated geometry tests.

All other test images (rotated, multi-face, no-face, corrupt, EXIF variants)
are generated deterministically from this file by `tests/conftest.py` at test
time and are never committed.
