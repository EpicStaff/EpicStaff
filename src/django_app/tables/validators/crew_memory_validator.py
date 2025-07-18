from tables.exceptions import CrewMemoryValidationError


class CrewMemoryValidator:
    """Validator class for crew memory configurations"""

    def validate_memory_configs(self, memory_llm_config, embedding_config):
        """
        Validate both memory LLM config and embedding config.
        Collects all validation errors and raises a single exception with all issues.

        Args:
            memory_llm_config: Memory LLM configuration to validate
            embedding_config: Embedding configuration to validate

        Raises:
            CrewMemoryValidationError: If any validation fails
        """
        errors = []

        try:
            self._validate_memory_llm_config(memory_llm_config)
        except CrewMemoryValidationError as e:
            errors.append(str(e))

        try:
            self._validate_embedding_config(embedding_config)
        except CrewMemoryValidationError as e:
            errors.append(str(e))

        if errors:
            error_message = "Memory configuration validation failed: " + "; ".join(
                errors
            )
            raise CrewMemoryValidationError(error_message)

    def _validate_memory_llm_config(self, memory_llm_config):

        if memory_llm_config is None:
            raise CrewMemoryValidationError(
                "Memory LLM configuration cannot be None. Please set the 'Memory LLM config'"
            )

    def _validate_embedding_config(self, embedding_config):

        if embedding_config is None:
            raise CrewMemoryValidationError(
                "Memory embedding configuration cannot be None. Please set the 'Memory embedding config'"
            )
