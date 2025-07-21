import asyncio
import os
import json
import re
import time
from typing import AsyncGenerator, AsyncIterable, Callable, Union
from abc import ABC, abstractmethod

from rest_framework import serializers
from loguru import logger
from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse, HttpResponse
from django.core.serializers.json import DjangoJSONEncoder
from django.views import View

from tables.models import DocumentMetadata, DocumentContent
from .file_text_extractor import extract_text_from_file

ALLOWED_FILE_TYPES = {choice[0] for choice in DocumentMetadata.DocumentFileType.choices}
MAX_FILE_SIZE = 12 * 1024 * 1024  # 12MB


class SourceSerializerMixin:
    """
    Mixin for validating file fields by size and file type(extension),
    validation of equal lenght of lists (files, chunk_sizes, chunk_strategies, chunk_overlaps)
    and creating DocumentMetadata and DocumentContent.
    """

    def validate_files_list(self, files):
        errors = {}
        for idx, uploaded_file in enumerate(files):
            file_errors = []
            if uploaded_file.size > MAX_FILE_SIZE:
                file_errors.append(f"{uploaded_file.name} exceeds 12MB limit.")
            ext = uploaded_file.name.split(".")[-1].lower()
            if ext not in ALLOWED_FILE_TYPES:
                file_errors.append(
                    f"{uploaded_file.name} has an invalid file type. Allowed types: {', '.join(ALLOWED_FILE_TYPES)}."
                )
            if file_errors:
                errors[f"files[{idx}]"] = file_errors
        if errors:
            raise serializers.ValidationError(errors)
        return files

    def validate_list_lengths(self, attrs):
        files = attrs.get("files")
        chunk_sizes = attrs.get("chunk_sizes")
        chunk_strategies = attrs.get("chunk_strategies")
        chunk_overlaps = attrs.get("chunk_overlaps")

        list_lengths = {
            "files": len(files),
            "chunk_sizes": len(chunk_sizes),
            "chunk_strategies": len(chunk_strategies),
            "chunk_overlaps": len(chunk_overlaps),
        }

        if len(set(list_lengths.values())) != 1:
            raise serializers.ValidationError(
                f"All list fields must have the same length. Received lengths: {list_lengths}"
            )

        return attrs

    def validate_list_document_metadata(self, list_document_metadata: list):
        errors = []
        for document_metadata in list_document_metadata:
            if not isinstance(document_metadata["document_content"], DocumentContent):
                errors.append(
                    f'The source file "{document_metadata["file_name"]}" to create a copy does not exist.'
                )

        if errors:
            raise serializers.ValidationError(errors)

    def _validate_jsons(self, list_of_objects: list) -> None:
        errors = []
        for obj in list_of_objects:
            try:
                self._validate_json(obj)
            except Exception as e:
                errors.append(e)
        if errors:
            raise serializers.ValidationError(errors)

    def _validate_json(self, obj) -> None:
        if not isinstance(obj, dict):
            raise serializers.ValidationError(f"Trying to pass invalid json: {obj}")

    def _convert_list_str_to_json(
        self, list_of_objects: list[str | dict]
    ) -> list[dict]:
        result = []

        for obj in list_of_objects:
            result.append(self._convert_str_to_json(obj))

        return result

    def _convert_str_to_json(self, obj) -> dict:
        if isinstance(obj, str):
            try:
                return json.loads(obj)
            except Exception as e:
                try:
                    safe_obj = re.sub(r"\\", r"\\\\", obj)
                    return json.loads(safe_obj)
                except Exception as e:
                    logger.error(f"Exception in '_convert_str_to_json': {e}")
                    return obj
        else:
            return obj

    def create_documents_for_collection(
        self,
        collection,
        files,
        chunk_sizes,
        chunk_strategies,
        chunk_overlaps,
        raw_additional_params,
    ):
        additional_params = self._convert_list_str_to_json(raw_additional_params)
        self._validate_jsons(additional_params)
        for (
            uploaded_file,
            chunk_size,
            chunk_strategy,
            chunk_overlap,
            additional_param,
        ) in zip(
            files, chunk_sizes, chunk_strategies, chunk_overlaps, additional_params
        ):
            file_type = uploaded_file.name.split(".")[-1].lower()
            extracted_text = extract_text_from_file(uploaded_file, file_type)
            document_content = DocumentContent.objects.create(
                content=extracted_text.encode("utf-8")
            )

            DocumentMetadata.objects.create(
                file_name=uploaded_file.name,
                file_type=file_type,
                source_collection=collection,
                chunk_size=chunk_size,
                chunk_strategy=chunk_strategy,
                chunk_overlap=chunk_overlap,
                additional_params=additional_param,
                document_content=document_content,
            )

            # TODO: Potential bug here: text extraction can take a long time.
            # Solution: save file in storage as is (without converting to binary data)
            # and than extract text / process images in knowledge container.

        return None

    def create_copy_collection(self, collection, list_document_metadata: list):
        self.validate_list_document_metadata(
            list_document_metadata=list_document_metadata
        )
        for document_metadata in list_document_metadata:

            additional_params = self._convert_str_to_json(
                document_metadata["additional_params"]
            )
            self._validate_json(additional_params)

            DocumentMetadata.objects.create(
                file_name=document_metadata["file_name"],
                file_type=document_metadata["file_type"],
                source_collection=collection,
                chunk_size=document_metadata["chunk_size"],
                chunk_strategy=document_metadata["chunk_strategy"],
                chunk_overlap=document_metadata["chunk_overlap"],
                additional_params=additional_params,
                document_content=document_metadata["document_content"],
            )

        return None


class SSEMixin(View, ABC):
    """
    A reusable mixin to stream server-sent events (SSE).
    Override `get_initial_data()` and `get_live_updates()` in your view.
    """

    ping_interval = 15  # seconds
    last_ping = None

    async def async_orm_generator(self, queryset):
        entities = await sync_to_async(list)(
            queryset
        )  # Convert queryset to a list asynchronously
        for entity in entities:
            yield entity  # Yield one entity at a time asynchronously

    @abstractmethod
    async def get_initial_data(self):
        """
        Overwrite this function with generator yielding initial data
        Each item should be either:
            - a dict with optional 'event' and required 'data' keys
            - or any JSON-serializable primitive (str, int, etc)
        """
        pass

    @abstractmethod
    async def get_live_updates(self):
        """
        Overwrite this function with generator yielding updates in while True loop
        Each item should be either:
            - a dict with optional 'event' and required 'data' keys
            - or any JSON-serializable primitive (str, int, etc)
        """
        pass

    async def _data_generator(
        self,
        callback: Callable[[], AsyncIterable[Union[dict, str, int, float, bool, None]]],
    ) -> AsyncGenerator[str, None]:
        """
        SSE data generator.

        Args:
            callback: A callable returning an async iterable of items.
                Each item should be either:
                    - a dict with optional 'event' and required 'data' keys
                    - or any JSON-serializable primitive (str, int, etc)

        Yields:
            str: Server-Sent Events (SSE) formatted strings.
        """

        async for item in callback():
            if isinstance(item, dict):
                if "event" in item:
                    yield f"event: {item['event']}\n"

                self.last_ping = time.time()
                yield f"data: {json.dumps(item.get('data', ''), cls=DjangoJSONEncoder)}\n\n"

            else:
                self.last_ping = time.time()
                yield f"data: {json.dumps(item, cls=DjangoJSONEncoder)}\n\n"

        # Yield a ping message if needed.
        if time.time() - self.last_ping > self.ping_interval:
            self.last_ping = time.time()
            yield ": ping\n\n"

    async def event_stream(self, test_mode=False):
        self.last_ping = time.time()
        try:
            async for data in self._data_generator(self.get_initial_data):
                yield data

            if test_mode:
                for i in range(3):
                    yield f"data: test event #{i + 1}\n\n"
                raise GeneratorExit()

            while True:
                async for data in self._data_generator(self.get_live_updates):
                    yield data

        except (GeneratorExit, KeyboardInterrupt):
            logger.warning("Sending fatal-error event due to manual stop")
            yield f"\n\nevent: fatal-error\ndata: event stream was stopped manually\n\n"
        except Exception as e:
            logger.error(f"Sending fatal-error event due to error: {e}")
            yield f"\n\nevent: fatal-error\ndata: unexpected error\n\n"

    async def get(self, request, *args, **kwargs):
        test_mode = bool(request.GET.get("test", ""))
        logger.debug(f"Started SSE {'with' if test_mode else 'without'} test mode")

        return StreamingHttpResponse(
            self.event_stream(test_mode=test_mode),
            content_type="text/event-stream",
            headers={
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )
