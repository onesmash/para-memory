#!/usr/bin/env python3
"""
Create a new entity in the knowledge graph.

Usage: python create_entity.py <base_path> <category> <name>
Category: projects, people, companies, resources
"""

import sys
import os
from pathlib import Path
import json
from datetime import datetime


def generate_entity_id(category, name):
    """Generate a unique entity ID."""
    # Simple ID generation - timestamp-based
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    clean_name = name.lower().replace(" ", "-")
    return f"{category}-{clean_name}-{timestamp}"


def create_summary(name, category):
    """Create summary.md template."""
    return f"""# {name}

## Overview

<!-- Brief description of this entity -->

## Hot Facts

<!-- Recently accessed facts (last 7 days) -->

## Warm Facts

<!-- Moderately recent facts (8-30 days) -->

## Related Entities

<!-- Links to related entities -->
"""


def create_items_json(entity_id):
    """Create initial items.json with empty array."""
    return {
        "entityId": entity_id,
        "created": datetime.now().isoformat(),
        "lastModified": datetime.now().isoformat(),
        "items": []
    }


def main():
    if len(sys.argv) != 4:
        print("Usage: python create_entity.py <base_path> <category> <name>")
        print("Category: projects, people, companies, resources")
        sys.exit(1)

    base_path = sys.argv[1]
    category = sys.argv[2]
    name = sys.argv[3]

    # Validate category
    valid_categories = {
        "projects": "projects",
        "people": "areas/people",
        "companies": "areas/companies",
        "resources": "resources"
    }

    if category not in valid_categories:
        print(f"Error: Invalid category. Must be one of: {', '.join(valid_categories.keys())}")
        sys.exit(1)

    # Create entity directory
    category_path = valid_categories[category]
    clean_name = name.lower().replace(" ", "-")
    entity_path = Path(base_path) / category_path / clean_name

    if entity_path.exists():
        print(f"Error: Entity already exists at {entity_path}")
        sys.exit(1)

    entity_path.mkdir(parents=True, exist_ok=True)

    # Create summary.md
    summary_content = create_summary(name, category)
    (entity_path / "summary.md").write_text(summary_content)

    # Create items.json
    entity_id = generate_entity_id(category, name)
    items_data = create_items_json(entity_id)
    (entity_path / "items.json").write_text(json.dumps(items_data, indent=2, ensure_ascii=False))

    print(f"✓ Created entity: {name}")
    print(f"  Location: {entity_path}")
    print(f"  Entity ID: {entity_id}")
    print(f"\nNext steps:")
    print(f"1. Edit {entity_path}/summary.md to add overview")
    print(f"2. Use update_entity.py to add facts")


if __name__ == "__main__":
    main()
