from services.graph.nodes.python_node import PythonNode
from models.request_models import PythonCodeData


class AudioTranscriptionNode(PythonNode):
    TYPE = "AUDIO_TRANSCRIPTION"

    def __init__(
        self,
        session_id,
        node_name,
        input_map,
        stop_event,
        output_variable_path,
        python_code_executor_service,
    ):
        if not input_map:
            raise ValueError(f"AudioTranscriptionNode input cannot be empty.")

        arg_names = input_map.keys()
        code_data = PythonCodeData(
            venv_name="default",
            code=self._get_code(arg_names),
            entrypoint="main",
            libraries=["faster_whisper", "pydub"],
        )

        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
            python_code_executor_service=python_code_executor_service,
            python_code_data=code_data,
        )

    def _get_code(self, arg_names: list[str]):
        return f"""

import os
import base64
import tempfile
from pydub import AudioSegment


def transcribe_audio(base64_audio: str):
    from faster_whisper import WhisperModel
    audio_bytes = base64.b64decode(base64_audio)

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(audio_bytes)
        input_path = tmp_file.name

    try:
        audio = AudioSegment.from_file(input_path)
        wav_path = tempfile.mktemp(suffix=".wav")
        audio.export(wav_path, format="wav")
    except Exception as e:
        os.remove(input_path)
        raise ValueError(f"Failed to process audio/video file: {{e}}")
    finally:
        os.remove(input_path)

    model = WhisperModel("medium", device="cpu", compute_type="int8")

    segments, info = model.transcribe(
        wav_path,
        word_timestamps=True,
        vad_filter=True
    )

    all_words = []
    for seg in segments:
        if hasattr(seg, 'words') and seg.words:
            for word in seg.words:
                all_words.append({{
                    "start": word.start,
                    "end": word.end,
                    "word": word.word
                }})

    results = []
    if all_words:
        current_speaker = 0
        current_segment = {{
            "speaker": f"SPEAKER_{{current_speaker:02d}}",
            "start": all_words[0]["start"],
            "words": [all_words[0]["word"]]
        }}
        
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
                current_segment = {{
                    "speaker": f"SPEAKER_{{current_speaker:02d}}",
                    "start": curr_word["start"],
                    "words": [curr_word["word"]]
                }}
            else:
                current_segment["words"].append(curr_word["word"])
        
        current_segment["end"] = all_words[-1]["end"]
        current_segment["text"] = "".join(current_segment["words"]).strip()
        results.append(current_segment)
    
    os.remove(wav_path)

    return results


def get_transcription(**files):
    content = dict()
    for key, file_ in files.items():
        content[key] = transcribe_audio(file_.base64_data)
    return content


def main({", ".join(arg_names)}):
    content = get_transcription({", ".join(f"{a}={a}" for a in arg_names)})
    return content
"""
