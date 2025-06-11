# game_server.py
import http.server
import socketserver
import json
from http import HTTPStatus
import threading
from queue import Queue

# --- Configuration ---
HTTP_SERVER_HOST = "0.0.0.0"
HTTP_SERVER_PORT = 8000

# Queue to store the latest sensor data
latest_sensor_data = Queue(maxsize=1)

# Store calibration offsets
calibration_data = {
    "o_alpha": 0,
    "o_beta": 0,
    "o_gamma": 0,
    "ax": 0,
    "ay": 0,
    "az": 0
}

class SensorHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/get_sensor_data':
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')  # Allow CORS
            self.end_headers()
            
            # Return the latest sensor data if available
            try:
                data = latest_sensor_data.get_nowait()
                latest_sensor_data.put(data)  # Put it back for next request
                
                # Apply calibration offsets
                calibrated_data = {
                    "o_alpha": data.get("o_alpha", 0) - calibration_data["o_alpha"],
                    "o_beta": data.get("o_beta", 0) - calibration_data["o_beta"],
                    "o_gamma": data.get("o_gamma", 0) - calibration_data["o_gamma"],
                    "ax": data.get("ax", 0) - calibration_data["ax"],
                    "ay": data.get("ay", 0) - calibration_data["ay"],
                    "az": data.get("az", 0) - calibration_data["az"]
                }

                # --- FIX: This is the critical change. ---
                # --- We must pass the quaternion data through. ---
                if "quat" in data:
                    calibrated_data["quat"] = data["quat"]
                
                self.wfile.write(json.dumps(calibrated_data).encode('utf-8'))
            except:
                # Provide a default structure with quat to prevent errors in the browser
                data = {"o_alpha": 0, "o_beta": 0, "o_gamma": 0, "ax": 0, "ay": 0, "az": 0, "quat": [1, 0, 0, 0]}
                self.wfile.write(json.dumps(data).encode('utf-8'))
            return
            
        return super().do_GET()

    def do_POST(self):
        if self.path == '/sensor_data':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                sensor_data = json.loads(post_data.decode('utf-8'))
                # Keep only the latest sensor data
                while not latest_sensor_data.empty():
                    latest_sensor_data.get()
                latest_sensor_data.put(sensor_data)
                
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON data")
            return
        
        elif self.path == '/calibrate':
            try:
                # Get the current sensor data for calibration
                data = latest_sensor_data.get_nowait()
                latest_sensor_data.put(data)  # Put it back
                
                # Store current values as calibration offsets
                global calibration_data
                calibration_data = {
                    "o_alpha": data["o_alpha"],
                    "o_beta": data["o_beta"],
                    "o_gamma": data["o_gamma"],
                    "ax": data["ax"],
                    "ay": data["ay"],
                    "az": data["az"]
                }
                
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "calibrated"}).encode('utf-8'))
            except:
                self.send_error(HTTPStatus.BAD_REQUEST, "No sensor data available for calibration")
            return

        return super().do_POST()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def run_http_server():
    with socketserver.TCPServer((HTTP_SERVER_HOST, HTTP_SERVER_PORT), SensorHandler) as httpd:
        print(f"HTTP server started on http://{HTTP_SERVER_HOST}:{HTTP_SERVER_PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    try:
        run_http_server()
    except KeyboardInterrupt:
        print("Server shutting down...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Exiting.")
