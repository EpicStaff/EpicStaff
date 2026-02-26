# Import/Export System Documentation

## Comprehensive Technical Documentation for Developers

This document provides detailed technical documentation for the Import/Export system, including architecture, workflows, and steps to add new entities or nodes.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Key Components](#key-components)
3. [How It Works](#how-it-works)
4. [Adding New Entities](#adding-new-entities)
5. [Adding New Nodes](#adding-new-nodes)
6. [IDMapper Functionality](#idmapper-functionality)

---

## System Overview

The `import_export` module is responsible for handling the import and export of various entities within the system. It provides a structured and extensible framework to manage data transfer between the application and external systems or files. The module is designed to ensure consistency, reusability, and ease of adding new entities to the import/export process.

---

## Key Components

| Component   | Purpose                                                                 |
|-------------|-------------------------------------------------------------------------|
| Serializers | Define how data is serialized and deserialized for each entity.         |
| Services    | Core logic for importing (`import_service.py`) and exporting data.      |
| Strategies  | Define specific behaviors for importing and exporting entities.         |
| Utilities   | Helper functions and constants to support import/export operations.     |
| Registry    | Maintains a registry of all entities that can be imported or exported.  |

---

## How It Works

The import/export process follows these steps:

1. **Entity Registration**: Each entity that supports import/export has its own strategy implemented in the `import_export/strategies/` directory. Every strategy should be registered in the `tables/apps.py` file to work.
2. **Data Serialization/Deserialization**: During import, data is deserialized using the appropriate serializer. During export, data is serialized into the desired format. Serializers are used almost exclusively for data representation, while object creation logic resides in strategies. Avoid specifying fields directly in serializers; use `__all__` or `exclude` to ensure new fields are automatically handled.
3. **Processing**: The import/export services use the registered strategies to process the data, including validation, transformation, and any entity-specific logic.
4. **Completion**: The processed data is either saved to the database (import) or written to a file or external system (export).

---

## Adding New Entities

To add a new entity to the import/export system, follow these steps:

1. **Create an EntityType**:
   - Add a new record to the `EntityType` enum in `enums.py`.
   - Add the entity to `DEPENDENCY_ORDER` in `constants.py`.

2. **Create a Serializer**:
   - Add a new file in the `serializers` directory (e.g., `my_entity.py`).
   - Define a serializer class for the entity, specifying how the data should be serialized and deserialized.

3. **Create a Strategy**:
   - Add a new file in the `strategies` directory (e.g., `my_entity.py`).
   - Define a strategy class for the entity using `EntityImportExportStrategy`.
   - Set the `entity_type` field to your newly created `EntityType`.
   - Set the `serializer_class` to your newly created serializer.
   - Override `extract_dependencies_from_instance()` if necessary.
   - Override `find_existing()` if logic is needed to find existing entities.
   - Override `create_entity()` to handle all creation logic for the entity.

4. **Register the Entity**:
   - Open the `tables/apps.py` file.
   - Add an entry for the new entity, linking it to its strategy.

**Note:** If unsure whether to create a separate entity, ask: "Can this object exist on its own?" If no, it should not be separated. If yes, create a separate strategy.

---

## Adding New Nodes

To add a new node to the import/export system, follow these steps:

1. **Create a NodeType**:
   - Add a new record to the `NodeType` enum in `enums.py`.

2. **Create a Serializer**:
   - Add a new serializer class in `serializers/graph.py` inheriting from `BaseNodeImportSerializer`.

3. **Register the Serializer for the Node**:
   - Add the new `NodeType` to `NODE_HANDLERS` in `strategies/node_handlers.py`.
   - Add a `"relation"` key to retrieve this type of node from the graph instance.
   - Create a separate `import_{node_name}_node` function if custom import logic is needed, and register it as an `"import_hook"` in `NODE_HANDLERS`.

**Note:** Most nodes do not require a separate import function. Use one only if the node depends on other entities in the system (e.g., `subgraph_node`).

---

## IDMapper Functionality

The `IDMapper` class tracks all entities created during the import/export process. Its primary functionality is to map the ID of an entity from the export file to the ID of the newly created entity. This ensures that relationships between objects in the original system are accurately recreated in the new system.

---

## FAQ

### What is the Main Entity?

When we mark something as the main entity, it means we skip the step where we check for an existing object during import. In other words, if the main entity is the one being imported, we always create a new instance.

For example, if we import an Agent that already exists in the system and Agent is the main entity, a duplicate will be created. This behavior is intentional: when importing a single top-level entity, it makes sense to create it explicitly, even if a similar object already exists.

---

### How to implement `find_existing()` with deep dependencies?

In our current implementation, we don’t want to go that far. If we truly needed to detect existing objects across multiple levels of dependencies — where each level must match exactly — we should consider generating hashes for those objects and comparing them instead.

However, given the current state of the system, the most reasonable approach is to perform only a shallow, surface-level check rather than attempting deep comparisons.

---
