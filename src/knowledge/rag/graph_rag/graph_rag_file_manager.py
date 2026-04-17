# TODO: move out string pathes to constants

import json
import os
from pathlib import Path
from typing import List, Optional, Dict
from loguru import logger

from graphrag.config.models.graph_rag_config import GraphRagConfig

from models.orm import GraphRagDocument

CONFIG_FILE_NAME = "graphrag_config.json"


class GraphRagFileManager:
    """
    Manages file system operations for GraphRAG indexing.

    GraphRAG requires a specific folder structure:
    ```
    graph_data/
    └── graph_rag_{id}/
        ├── .env                 # API keys
        ├── graphrag_config.json # Full graphrag config
        ├── input/               # Input documents for indexing
        │   ├── doc1.txt
        │   └── doc2.txt
        └── output/              # Generated index files (parquet)
            ├── entities.parquet
            ├── relationships.parquet
            ├── text_units.parquet
            └── ...
    ```
    """

    def __init__(self, base_dir: str | Path | None = None):
        """
        Initialize the file manager.

        Args:
            base_dir: Base directory for graph data storage.
                     If None, defaults to <project>/src/knowledge/graph_data
        """
        self._explicit_base = None if base_dir is None else Path(base_dir)

    def _find_src_dir(self) -> Path:
        """
        Find the 'src' directory by walking up from this file's location.
        Falls back to current working directory if not found.
        """
        current = Path(__file__).resolve()
        for parent in current.parents:
            if parent.name == "src":
                return parent
        logger.debug(
            "Could not find 'src' in parents; falling back to cwd() as project root."
        )
        return Path.cwd()

    def _resolve_base_dir(self) -> Path:
        """
        Determine the base directory for graph data storage.

        Resolution order:
        1. Explicit base_dir passed to constructor
        2. GRAPH_DATA_DIR environment variable (set in Docker)
        3. Auto-detect by walking up from __file__ to find 'src' (local dev)

        Returns:
            Absolute path to the base directory
        """
        if self._explicit_base:
            if self._explicit_base.is_absolute():
                return self._explicit_base.resolve()
            else:
                src_dir = self._find_src_dir()
                return (src_dir / self._explicit_base).resolve()

        env_dir = os.environ.get("GRAPH_DATA_DIR")
        if env_dir:
            return Path(env_dir).resolve()

        src_dir = self._find_src_dir()
        return (src_dir / "knowledge" / "graph_data").resolve()

    # ==================== Folder Operations ====================

    def get_or_create_root_folder(self, graph_rag_id: int) -> Path:
        """
        Ensure folder <base_dir>/graph_rag_{id} exists and return it.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            Path to the root folder

        Raises:
            ValueError: If graph_rag_id is invalid
            RuntimeError: If folder creation fails or path is outside base_dir
        """
        # Validate graph_rag_id
        try:
            graph_rag_id = int(graph_rag_id)
        except (TypeError, ValueError):
            raise ValueError("graph_rag_id must be an integer")

        base = self._resolve_base_dir()
        logger.debug(f"Resolved base graph_data dir: {base}")

        # Ensure base exists
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise RuntimeError(f"Failed to create base directory {base}: {exc}")

        # Construct target folder path
        folder = base / f"graph_rag_{graph_rag_id}"

        # Resolve and verify folder is inside base (security check)
        try:
            folder_resolved = folder.resolve()
        except Exception:
            folder_resolved = (base / f"graph_rag_{graph_rag_id}").absolute()

        try:
            folder_resolved.relative_to(base)
        except ValueError:
            raise RuntimeError(
                f"Refusing to create folder outside of base_dir. "
                f"base={base}, attempted={folder_resolved}"
            )

        # Create the folder
        try:
            folder_resolved.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create graph_rag folder {folder_resolved}: {exc}"
            )

        logger.info(f"Using graph_rag folder: {folder_resolved}")
        return folder_resolved

    def get_or_create_input_folder(self, root_folder: Path) -> Path:
        """
        Ensure 'input' subfolder exists inside the root folder.

        Args:
            root_folder: Root folder for the GraphRag

        Returns:
            Path to the input folder

        Raises:
            RuntimeError: If folder creation fails
        """
        input_folder = root_folder / "input"

        try:
            input_folder.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create 'input' folder inside {root_folder}: {exc}"
            )

        logger.debug(f"Input folder ready: {input_folder}")
        return input_folder

    def get_output_folder(self, root_folder: Path) -> Path:
        """
        Get the output folder path (where graphrag stores index files).

        Args:
            root_folder: Root folder for the GraphRag

        Returns:
            Path to the output folder
        """
        return root_folder / "output"

    # ==================== Document Loading ====================

    def load_documents_to_input(
        self,
        graph_rag_documents: List[GraphRagDocument],
        input_folder: Path,
    ) -> Dict[int, Path]:
        """
        Load documents from database storage to input folder as files.

        Takes GraphRagDocument objects (with document metadata and content loaded)
        and writes their content to the input folder for GraphRAG indexing.

        Args:
            graph_rag_documents: List of GraphRagDocument with loaded relationships
            input_folder: Path to the input folder

        Returns:
            Dict mapping graph_rag_document_id to file path

        Note:
            - Only processes documents that have content
            - Attempts UTF-8 decoding for text files
            - Falls back to replacement characters for binary files
        """
        loaded_files: Dict[int, Path] = {}

        for graph_doc in graph_rag_documents:
            doc_metadata = graph_doc.document

            if not doc_metadata:
                logger.warning(
                    f"GraphRagDocument {graph_doc.graph_rag_document_id} has no document metadata"
                )
                continue

            if (
                not doc_metadata.document_content
                or not doc_metadata.document_content.content
            ):
                logger.warning(
                    f"Document {doc_metadata.document_id} ({doc_metadata.file_name}) has no content"
                )
                continue

            # Determine file name
            file_name = (
                doc_metadata.file_name or f"document_{doc_metadata.document_id}.txt"
            )
            file_path = input_folder / file_name

            # Get binary content
            binary_content = doc_metadata.document_content.content

            # Convert to text (GraphRAG works with text files)
            try:
                text_content = self._decode_binary_content(binary_content)
            except Exception as e:
                logger.error(
                    f"Failed to decode document {doc_metadata.document_id}: {e}"
                )
                continue

            # Write to file
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(text_content)

                loaded_files[graph_doc.graph_rag_document_id] = file_path
                logger.info(f"Loaded document to: {file_path}")

            except Exception as e:
                logger.error(
                    f"Failed to write document {doc_metadata.document_id} to {file_path}: {e}"
                )

        logger.info(f"Loaded {len(loaded_files)} documents to input folder")
        return loaded_files

    def _decode_binary_content(self, binary_content: bytes) -> str:
        """
        Decode binary content to text string.

        Attempts UTF-8 first, then falls back to latin-1.

        Args:
            binary_content: Raw binary content from database

        Returns:
            Decoded text string
        """
        # Handle memoryview if needed
        if isinstance(binary_content, memoryview):
            binary_content = bytes(binary_content)

        # Try UTF-8 first
        try:
            return binary_content.decode("utf-8")
        except UnicodeDecodeError:
            pass

        # Try latin-1 (accepts all byte values)
        try:
            return binary_content.decode("latin-1")
        except UnicodeDecodeError:
            pass

        # Last resort: UTF-8 with replacement
        return binary_content.decode("utf-8", errors="replace")

    # ==================== Environment Setup ====================

    def setup_env_file(
        self,
        root_folder: Path,
        api_key: str,
        additional_vars: Optional[Dict[str, str]] = None,
    ) -> Path:
        """
        Create or update .env file in the graph_rag folder.

        Sets GRAPHRAG_API_KEY and any additional environment variables.

        Args:
            root_folder: Root folder for the GraphRag
            api_key: API key for GraphRAG operations
            additional_vars: Additional environment variables to set

        Returns:
            Path to the .env file
        """
        env_path = root_folder / ".env"

        # Read existing lines if file exists
        existing_lines = []
        if env_path.exists():
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()

        # Prepare variables to set
        vars_to_set = {"GRAPHRAG_API_KEY": api_key}
        if additional_vars:
            vars_to_set.update(additional_vars)

        # Track which variables we've updated
        updated_keys = set()

        # Update existing lines
        updated_lines = []
        for line in existing_lines:
            line_stripped = line.strip()

            # Check if this line sets any of our variables
            key_updated = False
            for key, value in vars_to_set.items():
                if line_stripped.startswith(f"{key}="):
                    updated_lines.append(f"{key}={value}")
                    updated_keys.add(key)
                    key_updated = True
                    break

            if not key_updated:
                updated_lines.append(line)

        # Add any variables that weren't in the file
        for key, value in vars_to_set.items():
            if key not in updated_keys:
                updated_lines.append(f"{key}={value}")

        # Write the updated .env content
        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

        logger.info(f"Updated .env file: {env_path}")
        return env_path

    # ==================== Cleanup Operations ====================

    def clean_input_folder(self, input_folder: Path) -> int:
        """
        Remove all files from the input folder after indexing.

        Args:
            input_folder: Path to the input folder

        Returns:
            Number of files removed
        """
        if not input_folder.exists():
            return 0

        removed_count = 0
        for file_path in input_folder.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    removed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to remove {file_path}: {e}")

        logger.info(f"Cleaned input folder: removed {removed_count} files")
        return removed_count

    def get_root_folder_path(self, graph_rag_id: int) -> Path:
        """
        Get the path to root folder without creating it.

        Useful for checking if index exists.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            Path to the root folder (may not exist)
        """
        base = self._resolve_base_dir()
        return base / f"graph_rag_{graph_rag_id}"

    def index_exists(self, graph_rag_id: int) -> bool:
        """
        Check if index output files exist for a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            True if output folder exists and contains parquet files
        """
        root_folder = self.get_root_folder_path(graph_rag_id)
        output_folder = root_folder / "output"

        if not output_folder.exists():
            return False

        # Check for key output files (community_reports needed for local search)
        required_files = [
            "entities.parquet",
            "relationships.parquet",
            "text_units.parquet",
            "community_reports.parquet",
        ]
        for file_name in required_files:
            if not (output_folder / file_name).exists():
                return False

        return True

    # ==================== Output Reading ====================

    def get_text_units_path(self, root_folder: Path) -> Path:
        """
        Get path to text_units.parquet file.
        """

        return root_folder / "output" / "text_units.parquet"

    def get_entities_path(self, root_folder: Path) -> Path:
        """
        Get path to entities.parquet file.
        """

        return root_folder / "output" / "entities.parquet"

    def get_relationships_path(self, root_folder: Path) -> Path:
        """
        Get path to relationships.parquet file.
        """

        return root_folder / "output" / "relationships.parquet"

    def get_communities_path(self, root_folder: Path) -> Path:
        """
        Get path to communities.parquet file.
        """

        return root_folder / "output" / "communities.parquet"

    # ==================== Config Persistence ====================

    def save_config(self, root_folder: Path, config: GraphRagConfig) -> Path:
        """
        Persist GraphRagConfig to JSON, stripping API keys for security.

        Args:
            root_folder: Root folder for the GraphRag
            config: GraphRagConfig instance to save

        Returns:
            Path to the saved config file
        """
        config_dict = config.model_dump(mode="json")

        # Strip api_key from every model entry
        for model_entry in config_dict.get("models", {}).values():
            if isinstance(model_entry, dict):
                model_entry["api_key"] = None

        config_path = root_folder / CONFIG_FILE_NAME
        config_path.write_text(
            json.dumps(config_dict, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"Saved GraphRagConfig to {config_path}")
        return config_path

    def load_config(self, root_folder: Path) -> GraphRagConfig:
        """
        Load GraphRagConfig from JSON, injecting API key from .env.

        Args:
            root_folder: Root folder for the GraphRag

        Returns:
            GraphRagConfig instance with API keys restored

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If API key not found in .env
        """
        config_path = root_folder / CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        config_dict = json.loads(config_path.read_text(encoding="utf-8"))

        # Inject API key into every model entry
        api_key = self._read_api_key_from_env(root_folder)
        for model_entry in config_dict.get("models", {}).values():
            if isinstance(model_entry, dict):
                model_entry["api_key"] = api_key

        return GraphRagConfig.model_validate(config_dict)

    def _read_api_key_from_env(self, root_folder: Path) -> str:
        """
        Read GRAPHRAG_API_KEY from .env file in root_folder.

        Args:
            root_folder: Root folder containing .env file

        Returns:
            API key string

        Raises:
            FileNotFoundError: If .env file doesn't exist
            ValueError: If GRAPHRAG_API_KEY not found in .env
        """
        env_path = root_folder / ".env"
        if not env_path.exists():
            raise FileNotFoundError(f".env file not found: {env_path}")

        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GRAPHRAG_API_KEY="):
                return line.split("=", 1)[1]

        raise ValueError(f"GRAPHRAG_API_KEY not found in {env_path}")
