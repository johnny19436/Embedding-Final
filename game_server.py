# game_server.py
import asyncio
import http.server
import ssl
import threading
import json
import websockets
import os
from pathlib import Path

# --- Configuration ---
HTTP_SERVER_HOST = "0.0.0.0"
HTTP_SERVER_PORT = 8000  # Port for serving HTML/JS files
WEBSOCKET_SERVER_HOST = "0.0.0.0"
WEBSOCKET_SERVER_PORT = 8765  # Port for WebSocket communication

# SSL Certificate (replace with your actual certificate and key files)
# You can generate a self-signed certificate for testing.
# Example using OpenSSL:
# openssl req -new -x509 -keyout key.pem -out cert.pem -days 365 -nodes
CERTFILE = "192.168.0.106.pem"
KEYFILE = "192.168.0.106-key.pem"

# --- Global state for WebSocket connections ---
# We'll have two types of clients: 'controller' (the phone) and 'game' (the browser)
controller_client = None
game_client = None
clients = set() # More generic client management

# --- WebSocket Server Logic ---
async def PINGPONG(websocket):
    '''
    Make sure connection is still/established
    '''
    await websocket.send(json.dumps({"type": "ping"}))
    try:
        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
        if json.loads(message).get("type") == "pong":
            return True
    except asyncio.TimeoutError:
        print("Pong not received")
    except json.JSONDecodeError:
        print("Invalid JSON received for pong")
    return False


async def websocket_handler(websocket, path):
    global controller_client, game_client, clients
    client_type = None
    clients.add(websocket)
    print(f"WebSocket client connected: {websocket.remote_address}")

    try:
        # First message determines client type (controller or game)
        initial_message = await websocket.recv()
        data = json.loads(initial_message)
        
        if data.get("type") == "controller_join":
            if controller_client and controller_client != websocket:
                print("A controller is already connected. Replacing.")
                try:
                    await controller_client.close(reason="New controller connected")
                except Exception:
                    pass # Ignore errors if already closed
            controller_client = websocket
            client_type = "controller"
            print("Controller client registered.")
            await websocket.send(json.dumps({"type": "controller_ack", "message": "Controller connected"}))

        elif data.get("type") == "game_join":
            if game_client and game_client != websocket:
                print("A game client is already connected. Replacing.")
                try:
                    await game_client.close(reason="New game client connected")
                except Exception:
                    pass
            game_client = websocket
            client_type = "game"
            print("Game client registered.")
            await websocket.send(json.dumps({"type": "game_ack", "message": "Game connected"}))
        else:
            print(f"Unknown initial message type: {data.get('type')}")
            await websocket.close(reason="Invalid initial message")
            return

        # Main message loop
        async for message in websocket:
            try:
                data = json.loads(message)
                # print(f"Received from {client_type}: {data}")

                if client_type == "controller":
                    # Controller sends motion data, forward to game client
                    if game_client and game_client.open:
                        # Add client type to the message for clarity on the game side
                        await game_client.send(json.dumps({"type": "bat_update", "data": data}))
                    else:
                        # print("Game client not connected, cannot forward controller data.")
                        pass
                elif client_type == "game":
                    # Game client might send game state or commands in the future
                    # For now, just log it
                    print(f"Message from game client: {data}")
                    if data.get("type") == "pong": # Handle pong for keep-alive
                        pass 
                    elif controller_client and controller_client.open: # Example: relay to controller
                         await controller_client.send(json.dumps({"type": "game_event", "data": data}))


            except json.JSONDecodeError:
                print(f"Invalid JSON received from {client_type}: {message}")
            except websockets.exceptions.ConnectionClosed:
                print(f"Connection closed by {client_type if client_type else 'unknown client'}.")
                break
            except Exception as e:
                print(f"Error processing message from {client_type}: {e}")
                break
                
    except websockets.exceptions.ConnectionClosedError:
        print(f"Client {websocket.remote_address} disconnected (closed error).")
    except websockets.exceptions.ConnectionClosedOK:
        print(f"Client {websocket.remote_address} disconnected (closed OK).")
    except Exception as e:
        print(f"Error in WebSocket connection with {websocket.remote_address}: {e}")
    finally:
        clients.remove(websocket)
        if websocket == controller_client:
            controller_client = None
            print("Controller client disconnected.")
        elif websocket == game_client:
            game_client = None
            print("Game client disconnected.")
        print(f"Client {websocket.remote_address} removed. Total clients: {len(clients)}")


async def start_websocket_server():
    # Setup SSL context for WSS
    ssl_context_ws = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_ws.load_cert_chain(CERTFILE, KEYFILE)
        print(f"WebSocket SSL context loaded using {CERTFILE} and {KEYFILE}")
    except FileNotFoundError:
        print(f"Error: SSL certificate or key file not found for WebSocket server.")
        print(f"Please create {CERTFILE} and {KEYFILE} or update the paths.")
        print("WebSocket server will run without SSL (ws://) if it's on localhost, but wss:// is needed for cross-origin device motion.")
        ssl_context_ws = None # Run without SSL if files not found
    except ssl.SSLError as e:
        print(f"SSL Error loading cert/key for WebSocket: {e}")
        ssl_context_ws = None


    server_args = {"host": WEBSOCKET_SERVER_HOST, "port": WEBSOCKET_SERVER_PORT}
    if ssl_context_ws:
        server_args["ssl"] = ssl_context_ws
        protocol = "wss"
    else:
        # Allow non-SSL only if binding to localhost for security
        if WEBSOCKET_SERVER_HOST not in ["localhost", "127.0.0.1", "0.0.0.0"]: # 0.0.0.0 can be problematic without SSL
             print(f"Warning: Running WebSocket server on {WEBSOCKET_SERVER_HOST} without SSL is insecure for device motion APIs.")
             print("It's highly recommended to use SSL (wss://).")
        protocol = "ws"


    async with websockets.serve(websocket_handler, **server_args):
        print(f"WebSocket server started on {protocol}://{WEBSOCKET_SERVER_HOST}:{WEBSOCKET_SERVER_PORT}")
        await asyncio.Future()  # Run forever

# --- HTTP Server Logic (modified from user's https_server.py) ---
class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve files from the current directory
        super().__init__(*args, directory=os.getcwd(), **kwargs)

    def guess_type(self, path):
        # Ensure JavaScript files are served with the correct MIME type
        if path.endswith(".js"):
            return "application/javascript"
        return super().guess_type(path)

def run_http_server():
    httpd = http.server.HTTPServer((HTTP_SERVER_HOST, HTTP_SERVER_PORT), CustomHTTPRequestHandler)
    
    # Setup SSL context for HTTPS
    ssl_context_http = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context_http.load_cert_chain(certfile=CERTFILE, keyfile=KEYFILE)
        print(f"HTTP SSL context loaded using {CERTFILE} and {KEYFILE}")
    except FileNotFoundError:
        print("Error: SSL certificate or key file not found for HTTPS server.")
        print(f"Please create {CERTFILE} and {KEYFILE} or update the paths.")
        print("HTTPS server cannot start without SSL certificates.")
        return
    except ssl.SSLError as e:
        print(f"SSL Error loading cert/key for HTTP: {e}")
        return

    httpd.socket = ssl_context_http.wrap_socket(httpd.socket, server_side=True)
    
    print(f"HTTPS server serving on https://{HTTP_SERVER_HOST}:{HTTP_SERVER_PORT}")
    print(f"Serving files from: {os.getcwd()}")
    print("Ensure 'controller.html', 'game.html', 'assets/', and 'js/' are in this directory.")
    httpd.serve_forever()

# --- Main Execution ---
if __name__ == "__main__":
    # Check if cert and key files exist
    if not Path(CERTFILE).exists() or not Path(KEYFILE).exists():
        print("-" * 40)
        print("SSL CERTIFICATE AND KEY NOT FOUND!")
        print(f"Please generate '{CERTFILE}' and '{KEYFILE}' and place them in the same directory as this script.")
        print("You can use OpenSSL: openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -sha256 -days 365 -nodes -subj \"/CN=localhost\"")
        print("Replace /CN=localhost with your server's IP or domain if not testing locally.")
        print("The game and controller will likely not work correctly without HTTPS/WSS.")
        print("-" * 40)
        # Decide if you want to exit or try to run without SSL (not recommended for production/device motion)
        # For this example, we'll proceed but WebSocket might fail or be insecure.
        # exit(1) # Uncomment to exit if certs are missing

    # Create dummy asset directories if they don't exist, to prevent server errors
    Path("assets/environment").mkdir(parents=True, exist_ok=True)
    Path("js").mkdir(parents=True, exist_ok=True)


    # Run HTTP server in a separate thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Run WebSocket server in the main thread (or another asyncio managed thread)
    try:
        asyncio.run(start_websocket_server())
    except KeyboardInterrupt:
        print("Servers shutting down...")
    except Exception as e:
        print(f"Main loop encountered an error: {e}")
    finally:
        # Potentially add cleanup here if http_thread needs explicit shutdown
        print("Exiting.")
