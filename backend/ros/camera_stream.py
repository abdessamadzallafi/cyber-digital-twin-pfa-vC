"""Camera stream metadata boundary (RTSP/WebRTC/Gazebo adapters can plug in)."""
from dataclasses import dataclass
import time


@dataclass
class CameraStream:
    stream_id: str = "drone_01_camera"
    url: str | None = None
    active: bool = False
    last_frame_at: float | None = None

    def start(self, url: str | None = None) -> dict:
        self.url = url or self.url
        self.active = True
        self.last_frame_at = time.time()
        return self.as_dict()

    def stop(self) -> dict:
        self.active = False
        return self.as_dict()

    def as_dict(self) -> dict:
        return {"stream_id": self.stream_id, "url": self.url, "active": self.active, "last_frame_at": self.last_frame_at}
