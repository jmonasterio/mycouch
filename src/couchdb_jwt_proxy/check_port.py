import os
import socket
import sys
from dotenv import load_dotenv

def check_port():
    # Load environment variables
    load_dotenv()
    
    # Get configuration
    host = os.getenv("PROXY_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("PROXY_PORT", "5985"))
    except ValueError:
        print(f"Error: Invalid PROXY_PORT value: {os.getenv('PROXY_PORT')}")
        sys.exit(1)
        
    print(f"Checking if port {port} is available on {host}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    
    try:
        # Try to bind to the port
        # If we can bind, it's available
        # We use bind instead of connect because we want to know if WE can listen on it
        # However, binding to 0.0.0.0 might succeed even if another interface is using it on some OSs
        # but usually it fails if the port is in use.
        
        # Note: On Windows, SO_REUSEADDR is default for bind, so we might need to be careful.
        # But usually for a simple check, attempting to bind will raise EADDRINUSE if taken.
        
        # Let's try to bind to the specific host first
        bind_host = host
        if host == "0.0.0.0":
            bind_host = "" # Bind to all interfaces
            
        sock.bind((bind_host, port))
        
        # If we got here, we successfully bound to the port.
        # Clean up and exit success
        sock.close()
        print(f"Port {port} is available.")
        sys.exit(0)
        
    except OSError as e:
        if e.errno == 10048 or "Address already in use" in str(e): # Windows specific error code for EADDRINUSE is 10048
            print(f"\n[ERROR] Port {port} is already in use!")
            print(f"Something is already listening on port {port}.")
            print(f"Please stop the existing process or change PROXY_PORT in your .env file.")
            print(f"You can check what's running with: netstat -ano | findstr :{port}")
            sys.exit(1)
        else:
            print(f"Error checking port {port}: {e}")
            sys.exit(1)
            
if __name__ == "__main__":
    check_port()
