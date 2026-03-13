import json
import base64

# ../buffer_out_data19-01-19-06-21.json
# ../buffer_out_data19-01-19-09-09.json
buffer_filename_base = [
    "../buffer_out_data19-01-20-20-54",
    "../buffer_in_data19-01-20-20-54",
]


def convert(buffer_filename_base_list: list[str]):
    for file_name_base in buffer_filename_base_list:
        with open(f"{file_name_base}.json", "r") as f:
            data = json.load(f)

        audio_bytes = b""

        for obj in data:
            audio_bytes += base64.b64decode(obj["audio"])

        # write to binary file
        with open(f"{file_name_base}.wav", "wb") as f:
            f.write(audio_bytes)


convert(buffer_filename_base_list=buffer_filename_base)
