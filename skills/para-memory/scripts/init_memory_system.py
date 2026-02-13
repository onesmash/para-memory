#!/usr/bin/env python3
"""
Initialize PARA memory system directory structure.

Usage: python init_memory_system.py <base_path>
"""

import sys
from pathlib import Path
from datetime import datetime


def create_directory_structure(base_path):
    """Create PARA directory structure."""
    base = Path(base_path)

    # Main PARA directories
    directories = [
        "projects",
        "areas/people",
        "areas/companies",
        "resources",
        "archives"
    ]

    for dir_path in directories:
        (base / dir_path).mkdir(parents=True, exist_ok=True)

    # Create index.md
    index_content = """# Knowledge Graph

This knowledge graph uses the PARA method to organize entities:

- **Projects/** - Active work with clear goals/deadlines
- **Areas/** - Ongoing responsibilities (no end date)
  - people/ - Individuals you know
  - companies/ - Organizations you work with
- **Resources/** - Topics of interest, reference material
- **Archives/** - Inactive items from any category

Each entity has:
- `summary.md` - Quick overview (loaded first)
- `items.json` - Atomic facts (loaded as needed)
"""
    (base / "index.md").write_text(index_content)

    return base


def main():
    if len(sys.argv) != 2:
        print("Usage: python init_memory_system.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]

    print(f"Initializing memory system at: {base_path}")

    # Create structures
    knowledge_base = create_directory_structure(base_path)
    print(f"✓ Created knowledge graph at: {knowledge_base}")

    print("\n✓ Memory system initialized successfully!")
    print("\nNext steps:")
    print("1. Create your first entity using create_entity.py")
    print("2. Set up QMD collections (see references/qmd_setup.md)")
    print("3. Start adding daily notes")


if __name__ == "__main__":
    main()
