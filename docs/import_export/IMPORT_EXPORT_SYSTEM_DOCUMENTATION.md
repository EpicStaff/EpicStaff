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
7. [Version Conversion](#version-conversion)

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
| Version Conversion | Migrates export JSON files from older versions to the current `IMPORT_VERSION` on import.  |

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
   - Add the corresponding `EntityType` record to the `EntityType` enum in `enums.py` (node types and entity types share the same string values).

2. **Add to Dependency Order**:
   - Add the new `EntityType` to `DEPENDENCY_ORDER` in `constants.py`.

3. **Create a Serializer**:
   - Add a new file in the `serializers/` directory, following the same pattern as other node serializers.

4. **Create a Strategy**:
   - Add a new file in the `strategies/` directory.
   - Define a strategy class inheriting from `EntityImportExportStrategy`.
   - Set `entity_type` to the new `EntityType`.
   - Set `serializer_class` to the new serializer.
   - Override `create_entity()` if the node has custom import logic.

5. **Register the Node Relation**:
   - Add the new `NodeType` to `NODE_RELATIONS` in `strategies/node_handlers.py`, mapping it to the reverse-relation accessor name on the `Graph` model.
   - `NODE_TYPE_TO_ENTITY_TYPE` is derived automatically from `NODE_RELATIONS` — no manual update needed.

6. **Register the Strategy**:
   - Open `tables/apps.py`.
   - Import the new strategy module and register it with `entity_registry.register(MyNodeStrategy())`.

**Note:** Most nodes do not require a custom `create_entity()` override. Add one only if the node depends on other entities tracked by the `IDMapper` (e.g., `subgraph_node`).

---

## IDMapper Functionality

The `IDMapper` class tracks all entities created during the import/export process. Its primary functionality is to map the ID of an entity from the export file to the ID of the newly created entity. This ensures that relationships between objects in the original system are accurately recreated in the new system.

---

## Version Conversion

The version conversion system allows import JSON files created with older versions of the export format to be automatically migrated to the current version before processing.

The current supported version is defined by `IMPORT_VERSION` in `tables/import_export/constants.py`. When an import file is read, `VersionConverter.convert()` checks its `"version"` field and applies registered migration functions in order until the data matches `IMPORT_VERSION`. Files without a `"version"` field are treated as version 1.

> **Note:** This mechanism operates exclusively on JSON export files. It does not apply to any other import sources.

### When to add a new converter

After a breaking change to the import/export format (e.g. renamed fields, restructured entities, or removed data), increment `IMPORT_VERSION` and register a converter that transforms data from the previous version.

### How to register a converter

Add a function to `tables/import_export/version_conversions/convertions.py` decorated with `@VersionConverter.register(from_version=N)`, where `N` is the version the function converts **from**. The function receives the current data dict and must return the updated dict. *Initial example is already in the that file*. 

The `convertions.py` module is auto-imported in `tables/apps.py`, so any decorator-registered function there is picked up at startup with no additional wiring required.

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
