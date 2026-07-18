#!/usr/bin/env python3

import socket
import json
import sys
import argparse


def handle_client(client_socket, channels):
    """Handle a single client connection"""
    while True:
        try:
            data = client_socket.recv(1024).decode("utf-8").strip()
            if not data:
                break
            
            print(f"[Server] Received: {data}")
            
            parts = data.split()
            
            if len(parts) == 0:
                continue
            
            command = parts[0]
            
            # Handle p command: p N 1|0
            if command == "p" and len(parts) == 3:
                try:
                    channel = int(parts[1])
                    state_value = int(parts[2])
                    
                    if 0 <= channel <= 6:
                        if state_value == 1:
                            channels[channel] = "passthrough"
                        elif state_value == 0:
                            channels[channel] = "idle"
                        
                        client_socket.send(b"OK\r\n")
                except (ValueError, IndexError):
                    pass
            
            # Handle s command: status
            elif command == "s":
                channel_list = [
                    {"ch": i, "state": channels[i]}
                    for i in range(7)
                ]
                response = json.dumps({"channels": channel_list})
                client_socket.send(response.encode("utf-8") + b"\r\n")
            
            # Handle q command: quit
            elif command == "q":
                break
        
        except Exception as e:
            print(f"[Server] Error: {e}")
            break
    
    client_socket.close()


def main():
    parser = argparse.ArgumentParser(description="Mock telnet server for weather-ctrl")
    parser.add_argument("--port", type=int, default=5555, help="Port to listen on (default: 5555)")
    
    args = parser.parse_args()
    port = args.port
    
    # Initialize channels (all start as "idle")
    channels = ["idle"] * 7
    
    # Create server socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("0.0.0.0", port))
    server_socket.listen(5)
    
    print(f"[Server] Listening on 0.0.0.0:{port}")
    
    try:
        while True:
            client_socket, addr = server_socket.accept()
            print(f"[Server] Client connected from {addr}")
            handle_client(client_socket, channels)
            print(f"[Server] Client disconnected from {addr}")
    except KeyboardInterrupt:
        print("\n[Server] Shutting down")
    finally:
        server_socket.close()


if __name__ == "__main__":
    main()
