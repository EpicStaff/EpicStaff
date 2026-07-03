# Python Code Tools Configuration

> ⚠️ **This document is obsolete.**
>
> The Python tool configuration system has been unified into the `variables` list. The old workflow with separate `PythonCodeToolConfigField` entities and the `/python-code-tool-config-fields/` endpoint no longer exists.
>
> See **[tools-configuration.md](tools-configuration.md)** for the current documentation.


This guide details the backend logic and workflow for creating dynamic configurations for Python tools. The feature enables the injection of variable settings (API keys, limits, URLs) directly into the tool's execution environment without modifying the source code.

## 🔑 Core Mechanism: Argument Injection

The central logic of this feature is the direct mapping between configuration fields and the Python function's arguments.

  * **Principle:** `Configuration Field Name` ➡️ `Function Argument Name`
  * **Mechanism:** When the tool executes, the backend automatically retrieves the active configuration, extracts the values, and passes them as keyword arguments (`**kwargs`) to the tool's `main` function.

### Code Example

If a configuration field is defined with the name `api_key`, the Python code must explicitly accept an argument with that exact name.

```python
# Backend passes: main(api_key="sk-...", limit=10)

def main(api_key, limit):
    # api_key receives the value "sk-..." automatically
    print(f"Connecting with {api_key}")
```

If the names do not match (e.g., field is `api_key` but code expects `my_key`), the variable will not be passed, resulting in a Python `TypeError` or missing argument error during execution.

-----

## ⚙️ Data Entities & Workflow

The backend process involves three main entities that function as a schema-instance relationship.

### 1\. Tool Definition (The Entity)

  * **Action:** Create a `PythonCodeTool`.
  * **Requirement:** The source code in this tool must contain a `main` function (or entry point) defined with specific arguments that correspond to the intended configuration fields.

### 2\. Configuration Schema (The Fields)

This defines the structure and validation rules for the configuration.

  * **Endpoint:** `POST /python-code-tool-config-fields/`
  * **Attributes:**
      * `tool`: Links to the specific `PythonCodeTool` ID.
      * `name`: **Must match the Python argument name** (e.g., `openai_api_key`).
      * `data_type`: Defines validation rules (`string`, `integer`, `boolean`, `float`).
      * `required`: Boolean flag indicating if the value is mandatory.
      * `default_value`: Fallback value used if the configuration instance does not provide one.

### 3\. Configuration Instance (The Values)

This is the actual set of values used during runtime.

  * **Endpoint:** `POST /python-code-tool-configs/`
  * **Attributes:**
      * `tool`: Links to the `PythonCodeTool`.
      * `name`: A label for this configuration set (e.g., "Production Creds").
      * `configuration`: A JSON object containing the actual key-value pairs (e.g., `{"openai_api_key": "sk-123..."}`).
  * **Backend Action:** Upon creation, the backend validates that the values in the JSON object match the types defined in the Configuration Fields (Schema).

-----

## 🛡️ Validation & Execution Behavior

The backend enforces specific rules during configuration creation and tool execution.

### Input Validation

  * **Data Types:** The backend validates input against the `data_type` defined in the field schema. Sending a string to an `integer` field results in a **400 Bad Request**.
  * **Required Fields:** If a field is marked `required=True`, creating a configuration without it results in a **400 Bad Request**.
  * **Extra Fields:** If the `configuration` JSON contains keys that do not exist in the defined Fields, the system ignores or strips them. It does **not** cause a crash.

### Execution Logic

When an Agent triggers the tool:

1.  **Retrieval:** The system loads the selected `PythonCodeToolConfig`.
2.  **Resolution:**
      * It pulls values from the `configuration` JSON.
      * If a value is missing in the JSON but has a `default_value` in the Field definition, the default is injected.
3.  **Injection:** The resolved dictionary is unpacked into the `main` function.
4.  **Error Handling:** If the code expects an argument that was not provided in the config (and has no default), the execution fails with a standard Python `TypeError`.