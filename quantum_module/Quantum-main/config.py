
from pathlib import Path

BASE_DIR = Path(__file__).parent

SHARED_DIR = BASE_DIR / "shared"
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"

VENUE = "MA Chidambaram Stadium"
CITY = "Chennai"

# Default signal limits
MIN_GREEN = 30
MAX_GREEN = 60
YELLOW = 5