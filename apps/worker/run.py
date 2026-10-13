"""Independent worker entrypoint; domain ownership stays in the backend package."""
from app.knowledge.worker import main

if __name__ == "__main__":
    main()
