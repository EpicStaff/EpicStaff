import os
from pathlib import Path
import platform
import shutil
import socket
import tempfile
import threading
import webbrowser

from flask import Flask, jsonify, render_template, Response, request
from flask_socketio import SocketIO, emit
import socketio

from app.utils import (
    init_env_file,
    save_savefiles_path,
    get_savefiles_path,
    select_folder,
    get_image_repository,
    save_image_repository,
    save_image_tag,
    get_image_tag,
)
from app.services.docker_service import DockerService
from app.services.docker_volume_manager import DockerVolumeManager
volume_manager = DockerVolumeManager("/tmp/docker_backups")

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

docker_service = DockerService()


def start_docker_monitoring():
    """Start monitoring Docker events in a background thread"""

    def monitor_events():
        def emit_container_statuses(container_statuses):
            socketio.emit("containers", container_statuses)

        docker_service.monitor_events(emit_container_statuses)

    thread = threading.Thread(target=monitor_events, daemon=True)
    thread.start()


@app.route("/")
def index():
    docker_ok, compose_ok = docker_service.check_docker_installed()
    return render_template(
        "index.html",
        docker_ok=docker_ok,
        compose_ok=compose_ok,
        location_type="input" if platform.system() == "Darwin" else "select",
        savefiles_path=get_savefiles_path(),
        image_repository=get_image_repository(),
        image_tag=get_image_tag(),
    )


@app.route("/export-volume/<volume_name>/download")
def export_volume(volume_name):
    """Export a Docker volume and return it as a downloadable file."""
    try:
        archive_path = volume_manager.export_volume(volume_name)
        return Response(
            archive_path.read_bytes(),
            mimetype="application/x-tar",
            headers={
                "Content-Disposition": f"attachment; filename={volume_name}.tar"
            },
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/import-volume/<volume_name>/upload", methods=["POST"])
def import_volume_upload(volume_name):
    """Import a Docker volume from an uploaded tar file."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as temp_file:
            file.save(temp_file)
            temp_file_path = Path(temp_file.name)

        volume_manager.import_volume(volume_name, temp_file_path)
        return jsonify({"message": f"Volume '{volume_name}' imported successfully."})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@socketio.on("get_state")
def get_state():
    try:
        emit("state", {"state": docker_service.get_state_name()})
    except Exception as e:
        emit("update_log", f"Error: {str(e)}")


@socketio.on("check_docker")
def handle_check_docker():
    docker_ok, compose_ok = docker_service.check_docker_installed()
    savefiles_path = get_savefiles_path()
    emit(
        "docker_status",
        {
            "docker_ok": docker_ok,
            "compose_ok": compose_ok,
            "savefiles_path": savefiles_path,
        },
    )


@socketio.on("update_images")
def handle_update_images(data):
    try:
        for line in docker_service.update_images(mode=data["mode"]):
            emit("update_log", line)
        emit("update_log", "Update process finished.")
    except Exception as e:
        emit("update_log", f"Error: {str(e)}")



@socketio.on("run_project")
def handle_run_project():
    try:
        for line in docker_service.run_project():
            emit("update_log", line)
        emit("update_log", "Project successfully started.")
    except Exception as e:
        emit("update_log", f"Error: {str(e)}")


@socketio.on("get_containers")
def handle_get_containers():
    try:
        statuses = docker_service.get_containers()
        emit("containers", statuses)
    except RuntimeError as e:
        emit("containers_error", {"error": str(e)})


@socketio.on("stop_container")
def handle_stop_container(data):
    try:
        docker_service.stop_container(data["container_id"])
        emit("action_success", "Container stopped successfully")
    except Exception as e:
        emit("action_error", str(e))


@socketio.on("restart_container")
def handle_restart_container(data):
    try:
        docker_service.restart_container(data["container_id"])
        emit("action_success", "Container restarted successfully")
    except Exception as e:
        emit("action_error", str(e))


@socketio.on("stop_project")
def handle_stop_project():
    try:
        docker_service.stop_project()
        emit("action_success", "Process stopped successfully")
    except Exception as e:
        emit("action_error", str(e))


@socketio.on("select_folder")
def handle_select_folder():
    try:
        path = select_folder()
        if save_savefiles_path(path):
            emit("folder_selected", {"success": True, "path": path})
        else:
            emit(
                "folder_selected", {"success": False, "error": "Error selecting folder"}
            )
    except Exception as e:
        emit("folder_selected", {"success": False, "error": str(e)})


@socketio.on("save_folder")
def handle_save_folder(data):
    try:
        path = data.get("path", "")
        if save_savefiles_path(path):
            emit("folder_selected", {"success": True, "path": path})
        else:
            emit(
                "folder_selected", {"success": False, "error": "Error selecting folder"}
            )
    except Exception as e:
        emit("folder_selected", {"success": False, "error": str(e)})


@socketio.on("save_image_repository")
def handle_save_image_repository(data):
    try:
        image_repository = data["image_repository"]
        if save_image_repository(image_repository):
            emit("image_repository_saved", {"success": True, "path": image_repository})
        else:
            emit(
                "image_repository_saved",
                {"success": False, "error": "Invalid repository path"},
            )
    except Exception as e:
        emit("image_repository_saved", {"success": False, "error": str(e)})


@socketio.on("save_image_tag")
def handle_save_image_tag(data):
    try:
        image_tag = data["image_tag"]
        if save_image_tag(image_tag):
            emit("image_tag_saved", {"success": True, "path": image_tag})
        else:
            emit("image_tag_saved", {"success": False, "error": "Invalid image tag"})
    except Exception as e:
        emit("image_tag_saved", {"success": False, "error": str(e)})


def is_port_in_use(port):
    """
    Checks if a given port is currently in use.
    Returns True if the port is in use, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return False  # Port is free
        except socket.error:
            return True  # Port is in use

def start_flask_app():
    """
    Starts the Flask application, dynamically finding an available port
    starting from 9000 if the initial port is in use.
    """
    if platform.system() == "Darwin":
        additional_paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
        current_path = os.environ.get("PATH", "")
        for p in additional_paths:
            if p not in current_path:
                os.environ["PATH"] += os.pathsep + p

    # Initial port to try
    port = 9000
    max_port_attempts = 100 # Limit the number of port attempts to avoid infinite loops

    # Find an available port
    found_port = False
    for _ in range(max_port_attempts):
        if not is_port_in_use(port):
            found_port = True
            break
        print(f"Port {port} is in use, trying next port...")
        port += 1
    
    if not found_port:
        print(f"Could not find an available port after {max_port_attempts} attempts, starting from 9000.")
        print("Please ensure no other applications are using a large range of ports.")
        input("Press Enter to exit...")
        return

    url = f"http://localhost:{port}"

    if not docker_service.ensure_docker_running():
        print("Docker is required to run this application.")
        input("Press Enter to exit...")
        return

    threading.Timer(1.0, lambda: webbrowser.open(url=url, new=0)).start()
    
    init_env_file(get_savefiles_path())
    start_docker_monitoring()

    print(f"Starting Flask app on port {port}...")
    app.run(port=port)