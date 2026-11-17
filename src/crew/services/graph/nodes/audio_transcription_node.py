from services.graph.exceptions import NodeConfigurationError
from services.graph.nodes.generated_code_node import GeneratedCodeNode
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials
from utils.node_label import runtime_node_name_to_label


class AudioTranscriptionNode(GeneratedCodeNode):
    TYPE = "AUDIO_TRANSCRIPTION"
    LABEL = "Audio to text node"

    def __init__(
        self,
        session_id,
        node_name,
        input_map,
        stop_event,
        output_variable_path,
        python_code_executor_service,
        storage_allowed_paths: list[str] | None = None,
        storage_org_prefix: str | None = None,
        org_id: int | None = None,
        storage_credentials: StorageCredentials | None = None,
    ):
        node = f'{self.LABEL} "{runtime_node_name_to_label(node_name)}"'
        if not input_map:
            raise NodeConfigurationError(f"{node} has no input file.")

        arg_names = input_map.keys()
        # TODO: this code imports faster_whisper and pydub, and needs PyAV below 19
        # (faster_whisper up to 1.2.1 calls av.open(metadata_errors=...), a keyword
        # PyAV 19 removed). Libraries now come only from the venv, and this node
        # declares none, so it runs in the sandbox's default venv and fails there
        # until it is given its own.
        code_data = PythonCodeData(
            code=_transcription_code(node, arg_names),
            entrypoint="main",
            use_storage=True,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
        )

        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
            python_code_executor_service=python_code_executor_service,
            python_code_data=code_data,
            storage_credentials=storage_credentials,
        )


def _transcription_code(node: str, arg_names) -> str:
    """Return the sandbox code that transcribes each input audio or video file.

    The code is ours, not the user's, so it reports its own failures: it exits 0 and
    returns `{"node.failure": <fact>, "node.debug": <traceback and the libraries' stderr>}`, and
    GeneratedCodeNode logs `debug` and streams only the fact. The fact names a known
    problem with the file or storage, or reads `<node> failed.` for anything else. On
    success the libraries' stderr is passed on.
    """
    arguments = ", ".join(arg_names)
    files = ", ".join(f"{name!r}: {name}" for name in arg_names)
    return (
        f"_NODE = {node!r}\n"
        + _TRANSCRIPTION_CODE
        + f"\n\ndef main({arguments}):\n    return _run({{{files}}})\n"
    )


_TRANSCRIPTION_CODE = r"""
import contextlib
import io
import os
import sys
import traceback
import tempfile


class _FileFailure(Exception):
    pass


def _file_name(file_path):
    return file_path.rsplit("/", 1)[-1]


def _read_bytes(file_path):
    from epicstaff_storage import StoragePermissionError, storage

    file_name = _file_name(file_path)
    try:
        return storage.read_bytes(file_path)
    except StoragePermissionError:
        raise _FileFailure(
            f"{_NODE} can't open \"{file_name}\": this flow has no access to it."
        )
    except FileNotFoundError:
        raise _FileFailure(f"{_NODE} can't find \"{file_name}\" in storage.")
    except Exception:
        raise _FileFailure(f"{_NODE} couldn't reach file storage.")


def _transcribe(file_path):
    audio_bytes = _read_bytes(file_path)
    from pydub import AudioSegment

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(audio_bytes)
        input_path = tmp_file.name

    try:
        audio = AudioSegment.from_file(input_path)
        wav_path = tempfile.mktemp(suffix=".wav")
        audio.export(wav_path, format="wav")
    except Exception:
        raise _FileFailure(f"{_NODE} can't process \"{_file_name(file_path)}\".")
    finally:
        os.remove(input_path)

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel("small", device="cpu", compute_type="int8")

        segments, info = model.transcribe(
            wav_path,
            word_timestamps=True,
            vad_filter=True
        )

        all_words = []
        for seg in segments:
            if hasattr(seg, 'words') and seg.words:
                for word in seg.words:
                    all_words.append({
                        "start": word.start,
                        "end": word.end,
                        "word": word.word
                    })

        results = []
        if all_words:
            current_speaker = 0
            current_segment = {
                "speaker": f"SPEAKER_{current_speaker:02d}",
                "start": all_words[0]["start"],
                "words": [all_words[0]["word"]]
            }

            silence_threshold = 1.5

            for i in range(1, len(all_words)):
                prev_word = all_words[i - 1]
                curr_word = all_words[i]

                pause = curr_word["start"] - prev_word["end"]

                if pause > silence_threshold:
                    current_segment["end"] = prev_word["end"]
                    current_segment["text"] = "".join(current_segment["words"]).strip()
                    results.append(current_segment)

                    current_speaker = (current_speaker + 1) % 2
                    current_segment = {
                        "speaker": f"SPEAKER_{current_speaker:02d}",
                        "start": curr_word["start"],
                        "words": [curr_word["word"]]
                    }
                else:
                    current_segment["words"].append(curr_word["word"])

            current_segment["end"] = all_words[-1]["end"]
            current_segment["text"] = "".join(current_segment["words"]).strip()
            results.append(current_segment)

        return results
    finally:
        os.remove(wav_path)


def _run(files):
    library_output = io.StringIO()
    with contextlib.redirect_stderr(library_output):
        try:
            result = {key: _transcribe(file_path) for key, file_path in files.items()}
        except Exception as error:
            fact = str(error) if isinstance(error, _FileFailure) else f"{_NODE} failed."
            return {"node.failure": fact, "node.debug": traceback.format_exc() + library_output.getvalue()}
    sys.stderr.write(library_output.getvalue())
    return result
"""
