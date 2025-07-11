import sys
from .importer import sync

def run() -> None:
    """Entry point for the Freshdesk MBOX Importer."""
    sync()

def main() -> None:
    """CLI dispatcher."""
    if len(sys.argv) == 2 and sys.argv[1] == "run":
        run()
    else:
        sys.stderr.write("Usage: python -m freshdesk_mbox_importer run\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
