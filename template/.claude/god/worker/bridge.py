"""Give the offline CLI a loopback HTTP endpoint backed by the WSL relay socket."""
import socket
import socketserver
import threading


def pump(source, destination):
    try:
        while data := source.recv(32768):
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Bridge(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.socket(socket.AF_UNIX) as upstream:
            upstream.connect("/relay/socket")
            thread = threading.Thread(target=pump, args=(self.request, upstream), daemon=True)
            thread.start()
            pump(upstream, self.request)
            thread.join()


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("127.0.0.1", 8183), Bridge) as server:
        server.serve_forever()
