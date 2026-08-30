import traceback

from greenhouse import main as run_greenhouse
from workday import main as run_workday
from simplify import main as run_simplify


def main():
    print("=== Greenhouse check ===")
    try:
        run_greenhouse()
    except Exception:
        traceback.print_exc()

    print("=== Workday check ===")
    try:
        run_workday()
    except Exception:
        traceback.print_exc()

    print("=== SimplifyJobs check ===")
    try:
        run_simplify()
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()
